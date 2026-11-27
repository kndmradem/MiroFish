import { BulkPage } from "@/components/collection/bulk-page";

/** Koleksiyonu olmayan ürünleri toplu yükle; panel her ürünü ayrı değerlendirir (tekli ekranın toplu hali). */
export default function BulkItemsPage() {
  return <BulkPage kind="bagimsiz" />;
}
