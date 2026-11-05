// Run with: npm test  (node --test, no extra dependencies)
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  cardIdFromSlug,
  cardSlug,
  date,
  direction,
  isoWeek,
  isLang,
  jsonLd,
  pct,
  polyline,
  slugify,
  term,
  vnd,
  vndShort,
  weekStart,
} from "../lib/format.ts";

const nbsp = (s: string) => s.replace(/\u00a0|\u202f/g, " ");

test("money in Vietnamese and English", () => {
  assert.equal(nbsp(vnd(1_499_000, "vi")), "1.499.000 ₫");
  assert.equal(vnd(1_499_000, "en"), "₫1,499,000");
  assert.equal(vndShort(1_500_000_000, "vi"), "1,5 tỷ");
  assert.equal(vndShort(5_000_000, "en"), "5M");
  assert.equal(vndShort(999, "en"), "999");
});

test("rates keep two decimals, the way banks write them", () => {
  assert.equal(pct("5.900", "vi"), "5,90%");
  assert.equal(pct("5.900", "en"), "5.90%");
  assert.equal(pct("2.595", "en"), "2.595%");
  assert.equal(pct(6, "vi"), "6,00%");
});

test("dates in Vietnam time", () => {
  // 20:00 UTC on the 27th is already the 28th in Hanoi
  assert.equal(date("2026-10-27T20:00:00Z", "vi"), "28/10/2026");
  assert.equal(date("2026-10-28", "en"), "28 Oct 2026");
  assert.equal(date(null, "vi"), "—");
});

test("slugs and card ids", () => {
  assert.equal(slugify("Thẻ tín dụng Đông Á Visa"), "the-tin-dung-dong-a-visa");
  assert.equal(cardSlug("Techcombank Visa Signature", 12), "techcombank-visa-signature-12");
  assert.equal(cardIdFromSlug("techcombank-visa-signature-12"), 12);
  assert.equal(cardIdFromSlug("42"), 42);
  assert.equal(cardIdFromSlug("no-id"), null);
});

test("terms", () => {
  assert.equal(term(12, 0, "vi"), "12 tháng");
  assert.equal(term(1, 0, "en"), "1 month");
  assert.equal(term(0, 7, "vi"), "7 ngày");
  assert.equal(term(0, 0, "en"), "Demand");
});

test("weeks start on Monday, Vietnam time", () => {
  assert.equal(weekStart("2026-10-28T03:00:00Z"), "2026-10-26"); // Wednesday
  assert.equal(weekStart("2026-10-25T18:00:00Z"), "2026-10-26"); // Sunday 18:00 UTC = Monday 01:00
  assert.equal(weekStart("2026-10-26T00:00:00Z"), "2026-10-26");
  assert.equal(isoWeek("2026-10-26"), 44);
  assert.equal(isoWeek("2026-12-28"), 53);
  assert.equal(isoWeek("2027-01-04"), 1);
});

test("change direction", () => {
  assert.equal(direction("6.00", "6.20"), 1);
  assert.equal(direction("6.20", "6.00"), -1);
  assert.equal(direction("6.0", "6.00"), 0);
  assert.equal(direction(null, "6.00"), 0);
  assert.equal(direction("Golf", "Spa"), 0);
});

test("chart scaling", () => {
  const box = { width: 100, height: 50, tMin: 0, tMax: 10, vMin: 5, vMax: 6 };
  assert.equal(polyline([{ t: 0, v: 5 }, { t: 10, v: 6 }], box), "0.0,50.0 100.0,0.0");
  assert.equal(polyline([{ t: 3, v: 5 }], { ...box, tMax: 0, tMin: 0, vMin: 5, vMax: 5 }), "50.0,25.0");
});

test("JSON-LD can't break out of its script tag", () => {
  assert.equal(jsonLd({ name: "</script><script>alert(1)" }), '{"name":"\\u003c/script>\\u003cscript>alert(1)"}');
});

test("languages", () => {
  assert.ok(isLang("vi") && isLang("en"));
  assert.ok(!isLang("fr"));
});
