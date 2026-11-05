import Link from "next/link";

/** Shown inside the [lang] layout. Bilingual: the language isn't known here. */
export default function NotFound() {
  return (
    <div className="sv-container space-y-4 py-24 text-center">
      <p className="t-label text-jade">404</p>
      <h1 className="t-display">Không tìm thấy trang này</h1>
      <p className="text-muted">Page not found.</p>
      <p className="flex justify-center gap-3">
        <Link href="/" className="sv-btn sv-btn--primary">
          Về trang chủ
        </Link>
        <Link href="/en" className="sv-btn sv-btn--secondary">
          Home
        </Link>
      </p>
    </div>
  );
}
