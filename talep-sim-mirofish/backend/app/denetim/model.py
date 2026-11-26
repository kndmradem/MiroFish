"""Mantık denetimi veri modeli. Bağımlılığı yalnızca pydantic: app.models ve koleksiyon modelleri bunu içe aktarır."""
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

Seviye = Literal["hata", "uyarı", "bilgi"]
Durum = Literal["temiz", "uyarılı", "incelenmeli"]
SIRA = {"hata": 0, "uyarı": 1, "bilgi": 2}


class Bulgu(BaseModel):
    seviye: Seviye
    kural: str = Field(..., description="Kural kodu (ör. kategori_disi_eslesme); regresyon vakaları bu koda bakar")
    baslik: str = Field(..., description="Kuralın kısa adı")
    mesaj: str
    skus: List[str] = Field(default_factory=list)
    bolge: Optional[str] = None
    alan: Optional[str] = Field(None, description="Sonuçtaki yer (ör. summary.cannibal_pairs[1])")
    dayanak: str = Field("kural varsayımı", description="Denetlenen sayının dayanağı (ajan / kural varsayımı / ...) ya da denetimin eşiği")


class DenetimRaporu(BaseModel):
    durum: Durum = Field(..., description="temiz: bulgu yok ya da yalnızca bilgi; uyarılı: uyarı var; incelenmeli: en az bir hata")
    ozet: str
    sayilar: Dict[str, int] = Field(default_factory=dict)
    bulgular: List[Bulgu] = Field(default_factory=list)
    kurallar: List[str] = Field(default_factory=list, description="Çalışan kural kodları")
    kapsam: str = Field("", description="koleksiyon / tekli / veri")
    surum: str = ""
    sinir: str = Field("Denetim kural tabanlıdır: sonucun kendi içinde tutarlı olup olmadığını ölçer, doğru olup olmadığını "
                      "ölçmez. Ajanların ham cevapları ve görsel-ürün eşleşmesi insan gözüyle kontrol edilmelidir.")

    @property
    def incelenmeli(self) -> bool:
        return self.durum == "incelenmeli"
