"""Zep'siz kişi listesi ("yerel grafik").

Talep simülasyonu MiroFish'e tek tek tanımlı kişiler verir (ad, yaş, cinsiyet, şehir, ebeveynlik...). Bu kişileri
Zep bilgi grafiğinden çıkarmaya gerek yoktur: liste doğrudan proje klasörüne yazılır, proje grafiği
`local_<project_id>` adıyla "kurulmuş" sayılır ve simülasyon hazırlığı varlıkları buradan okur. Zep API anahtarı,
internet ve bulut gerekmez. Kişi alanları (yaş, cinsiyet, ülke, meslek) profil üretiminde LLM'in tahmininin
önüne geçer.
"""
import json
import os
import uuid
from typing import Any, Dict, List, Optional

from .zep_entity_reader import EntityNode, FilteredEntities

LOCAL_PREFIX = "local_"
FILE_NAME = "local_entities.json"


def is_local(graph_id: Optional[str]) -> bool:
    return bool(graph_id) and str(graph_id).startswith(LOCAL_PREFIX)


def _path(project_id: str) -> str:
    from ..models.project import ProjectManager
    return os.path.join(ProjectManager._get_project_dir(project_id), FILE_NAME)


def save_people(project_id: str, people: List[Dict[str, Any]]) -> str:
    """Kişileri kaydeder, yerel graph_id döner. Her kişi: name (zorunlu), summary, type, attributes."""
    clean = []
    for p in people:
        name = str(p.get("name") or "").strip()
        if not name:
            raise ValueError("Her kişinin name alanı olmalı")
        clean.append({"uuid": p.get("uuid") or uuid.uuid5(uuid.NAMESPACE_URL, f"{project_id}/{name}").hex,
                      "name": name, "type": str(p.get("type") or "Person"),
                      "summary": str(p.get("summary") or ""), "attributes": dict(p.get("attributes") or {})})
    if len({c["name"] for c in clean}) != len(clean):
        raise ValueError("Kişi adları benzersiz olmalı")
    with open(_path(project_id), "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=1)
    return f"{LOCAL_PREFIX}{project_id}"


def load_entities(graph_id: str, defined_entity_types: Optional[List[str]] = None) -> FilteredEntities:
    project_id = graph_id[len(LOCAL_PREFIX):]
    with open(_path(project_id), encoding="utf-8") as f:
        people = json.load(f)
    ents = [EntityNode(uuid=p["uuid"], name=p["name"], labels=["Entity", p["type"]], summary=p["summary"],
                       attributes=p["attributes"]) for p in people
            if not defined_entity_types or p["type"] in defined_entity_types]
    return FilteredEntities(entities=ents, entity_types={e.labels[1] for e in ents},
                            total_count=len(people), filtered_count=len(ents))


AUTHORITATIVE = ("age", "gender", "country", "profession")


def apply_attributes(profile_data: Dict[str, Any], attributes: Dict[str, Any]) -> Dict[str, Any]:
    """Kişi listesinde verilen yaş/cinsiyet/ülke/meslek LLM'in ürettiğinin yerine geçer."""
    out = dict(profile_data)
    for k in AUTHORITATIVE:
        v = attributes.get(k)
        if v not in (None, ""):
            out[k] = int(v) if k == "age" and str(v).isdigit() else v
    return out
