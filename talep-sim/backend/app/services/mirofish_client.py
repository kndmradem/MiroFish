"""MiroFish Flask API'si için ince async istemci.

Kullanılan uç noktalar (MiroFish backend/app/api):
  POST /api/graph/ontology/generate   seed dokümanı yükle -> project_id
  POST /api/graph/build               Zep bilgi grafiğini kur -> task_id
  GET  /api/graph/task/<id>           görev durumu
  POST /api/simulation/create         -> simulation_id
  POST /api/simulation/prepare        persona/ajan profillerini üret -> task_id
  POST /api/simulation/prepare/status
  POST /api/simulation/start          simülasyonu başlat (bitince ortam komut bekler)
  POST /api/simulation/env-status     ortam röportaja hazır mı
  GET  /api/simulation/<id>/profiles  ajan profilleri
  POST /api/simulation/interview/batch
"""
import asyncio
from typing import Any, Dict, List, Optional

import httpx


class MiroFishError(RuntimeError):
    pass


class MiroFishTimeout(MiroFishError):
    """Yavaş model yüzünden zaman aşımı (HTTP 504, "IPC yanıt zaman aşımı" ya da istemci timeout'u)."""


_TIMEOUT_HINTS = ("timeout", "timed out", "超时")


class MiroFishClient:
    def __init__(self, base_url: str, client: Optional[httpx.AsyncClient] = None, build_timeout: float = 1800):
        # Dünya kurma çağrıları (ontoloji üretimi vb.) yerel modelde onlarca dakika sürebilir: ayrı, uzun timeout.
        self.build_timeout = build_timeout
        self.client = client or httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=300)

    async def _call(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        try:
            resp = await self.client.request(method, path, **kwargs)
        except httpx.TimeoutException as e:
            raise MiroFishTimeout(
                f"MiroFish yanıt vermedi ({path}): {type(e).__name__}: {e or 'zaman aşımı'}. "
                "Model hâlâ önceki isteği işliyor olabilir; terminalde `ollama ps` ile kontrol et.") from e
        except httpx.HTTPError as e:
            raise MiroFishError(f"MiroFish'e ulaşılamadı ({path}): {type(e).__name__}: {e}") from e
        try:
            body = resp.json()
        except ValueError:
            raise MiroFishError(f"{path} JSON olmayan cevap döndü ({resp.status_code})")
        if resp.status_code >= 400 or not body.get("success", False):
            err = str(body.get("error"))
            if resp.status_code == 504 or any(h in err.lower() for h in _TIMEOUT_HINTS):
                raise MiroFishTimeout(f"{path} zaman aşımı ({resp.status_code}): {err}")
            raise MiroFishError(f"{path} başarısız ({resp.status_code}): {err}")
        return body["data"]

    async def generate_ontology(self, filename: str, document: str, requirement: str, project_name: str) -> str:
        data = await self._call(
            "POST", "/api/graph/ontology/generate",
            files={"files": (filename, document.encode(), "text/markdown")},
            data={"simulation_requirement": requirement, "project_name": project_name},
            timeout=self.build_timeout,
        )
        return data["project_id"]

    async def build_graph(self, project_id: str) -> str:
        data = await self._call("POST", "/api/graph/build", json={"project_id": project_id}, timeout=self.build_timeout)
        return data["task_id"]

    async def wait_graph_task(self, task_id: str, poll_s: float = 5, timeout_s: float = 1800) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while True:
            task = await self._call("GET", f"/api/graph/task/{task_id}")
            if task["status"] == "completed":
                return task
            if task["status"] == "failed":
                raise MiroFishError(f"Grafik görevi başarısız: {task.get('error')}")
            if loop.time() > deadline:
                raise MiroFishError("Grafik görevi zaman aşımına uğradı")
            await asyncio.sleep(poll_s)

    async def create_simulation(self, project_id: str) -> str:
        data = await self._call("POST", "/api/simulation/create", json={
            "project_id": project_id, "enable_twitter": False, "enable_reddit": True}, timeout=self.build_timeout)
        return data["simulation_id"]

    async def prepare(self, simulation_id: str) -> Optional[str]:
        data = await self._call("POST", "/api/simulation/prepare", json={"simulation_id": simulation_id},
                                timeout=self.build_timeout)
        return None if data.get("already_prepared") else data.get("task_id")

    async def wait_prepared(self, simulation_id: str, task_id: Optional[str], poll_s: float = 5, timeout_s: float = 1800) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while True:
            body = {"simulation_id": simulation_id}
            if task_id:
                body["task_id"] = task_id
            st = await self._call("POST", "/api/simulation/prepare/status", json=body)
            if st.get("already_prepared") or st["status"] in ("ready", "completed"):
                return
            if st["status"] == "failed":
                raise MiroFishError(f"Simülasyon hazırlığı başarısız: {st.get('message')}")
            if loop.time() > deadline:
                raise MiroFishError("Simülasyon hazırlığı zaman aşımına uğradı")
            await asyncio.sleep(poll_s)

    async def start(self, simulation_id: str, max_rounds: int) -> None:
        await self._call("POST", "/api/simulation/start", json={
            "simulation_id": simulation_id, "platform": "reddit", "max_rounds": max_rounds},
            timeout=self.build_timeout)

    async def env_alive(self, simulation_id: str) -> bool:
        data = await self._call("POST", "/api/simulation/env-status", json={"simulation_id": simulation_id})
        return bool(data.get("env_alive"))

    async def profiles(self, simulation_id: str) -> List[Dict[str, Any]]:
        data = await self._call("GET", f"/api/simulation/{simulation_id}/profiles", params={"platform": "reddit"})
        return data["profiles"]

    async def interview_batch(self, simulation_id: str, agent_ids: List[int], prompt: str, timeout: int) -> Dict[int, str]:
        data = await self._call("POST", "/api/simulation/interview/batch", json={
            "simulation_id": simulation_id,
            "platform": "reddit",
            "timeout": timeout,
            "interviews": [{"agent_id": a, "prompt": prompt} for a in agent_ids],
        }, timeout=timeout + 30)
        results = (data.get("result") or {}).get("results") or {}
        return {int(r["agent_id"]): r.get("response", "") for r in results.values() if "agent_id" in r}
