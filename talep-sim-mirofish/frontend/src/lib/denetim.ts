/** Mantık denetimi: sonucun kendi içinde tutarlılığı (backend app/denetim). */
export type Seviye = "hata" | "uyarı" | "bilgi";

export interface Bulgu {
  seviye: Seviye;
  kural: string;
  baslik: string;
  mesaj: string;
  skus: string[];
  bolge?: string | null;
  alan?: string | null;
  dayanak: string;
}

export interface DenetimRaporu {
  durum: "temiz" | "uyarılı" | "incelenmeli";
  ozet: string;
  sayilar: Record<Seviye, number>;
  bulgular: Bulgu[];
  kurallar: string[];
  kapsam: string;
  surum: string;
  sinir: string;
}
