"use client";

import Link from "next/link";
import { useState } from "react";

import type { Lang } from "@/lib/format";
import { href } from "@/lib/i18n";
import { complete, profile, QUESTIONS, type Answers, type Note, type Profile } from "@/lib/riskProfile";

export type QuizPortfolio = { id: string; name: string; summary: string };

const TEXT = {
  vi: {
    ability: "Khả năng chịu rủi ro",
    abilityHint: "Hoàn cảnh của bạn cho phép chịu rủi ro đến đâu.",
    willingness: "Mức sẵn lòng chịu rủi ro",
    willingnessHint: "Bạn thấy thoải mái với biến động đến đâu.",
    submit: "Xem kết quả",
    missing: "Hãy trả lời tất cả câu hỏi.",
    result: "Kết quả của bạn",
    levels: ["", "Rất thấp", "Thấp", "Trung bình", "Khá cao", "Cao"],
    suggested: "Danh mục mẫu phù hợp",
    why: "Gợi ý theo mức thấp hơn trong hai điểm số: không nên chịu rủi ro nhiều hơn mức hoàn cảnh cho phép, cũng không nhiều hơn mức bạn có thể kiên nhẫn giữ.",
    goal: "Tính khả năng đạt mục tiêu với danh mục này",
    all: "Xem cả 5 danh mục mẫu",
    split: "Chia tài sản theo mục tiêu",
    notes: {
      loss_aversion:
        "Bạn chọn phương án lợi nhuận cao nhưng sẽ bán khi giảm 20%. Danh mục nhiều cổ phiếu thường giảm như vậy vài lần trong 10 năm, và bán lúc giảm là cách mất tiền phổ biến nhất. Hãy chọn mức mà bạn chắc chắn sẽ giữ được.",
      overconfidence:
        "Bạn sẵn sàng chịu rủi ro cao nhưng chưa có nhiều kinh nghiệm. Có thể bắt đầu thấp hơn một bậc, rồi tăng dần khi đã quen với biến động.",
      capacity_limits:
        "Bạn sẵn lòng chịu rủi ro nhiều hơn mức hoàn cảnh cho phép (quỹ dự phòng, thu nhập, nợ). Xây quỹ dự phòng đủ 6 tháng chi tiêu trước sẽ giúp nâng mức này.",
      short_horizon: "Bạn cần tiền trong vài năm tới, nên danh mục thận trọng phù hợp hơn dù bạn sẵn lòng chịu rủi ro.",
    } satisfies Record<Note, string>,
    note: "Bảng hỏi chạy trên máy của bạn; SoiVí không lưu câu trả lời. Kết quả để tham khảo, không phải lời khuyên đầu tư cho cá nhân bạn.",
  },
  en: {
    ability: "Ability to take risk",
    abilityHint: "How much risk your situation can carry.",
    willingness: "Willingness to take risk",
    willingnessHint: "How comfortable you are with ups and downs.",
    submit: "See the result",
    missing: "Please answer every question.",
    result: "Your result",
    levels: ["", "Very low", "Low", "Medium", "Fairly high", "High"],
    suggested: "Matching model portfolio",
    why: "The suggestion follows the lower of the two scores: take no more risk than your situation can carry, and no more than you can sit through.",
    goal: "Check the chance of reaching your goal with it",
    all: "See all five model portfolios",
    split: "Split your money by goal",
    notes: {
      loss_aversion:
        "You chose a high-return option but would sell after a 20% fall. Equity-heavy portfolios fall that much a few times in ten years, and selling in a fall is the most common way to lose money. Choose a level you are sure you will hold.",
      overconfidence:
        "You are ready for high risk but have little experience. Consider starting one level lower and moving up once you are used to the swings.",
      capacity_limits:
        "You are willing to take more risk than your situation allows (emergency fund, income, debt). Building a six-month emergency fund first would raise it.",
      short_horizon: "You need the money within a few years, so a cautious portfolio fits better even though you are willing to take risk.",
    } satisfies Record<Note, string>,
    note: "The questionnaire runs on your device; SoiVí stores no answers. For reference only, not personal investment advice.",
  },
};

export function RiskQuiz({ lang, portfolios }: { lang: Lang; portfolios: QuizPortfolio[] }) {
  const x = TEXT[lang];
  const [answers, setAnswers] = useState<Answers>({});
  const [result, setResult] = useState<Profile | null>(null);
  const [missing, setMissing] = useState(false);

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!complete(answers)) {
      setMissing(true);
      return;
    }
    setMissing(false);
    setResult(profile(answers));
  }

  const suggested = result ? portfolios[Math.min(result.level, portfolios.length) - 1] : undefined;

  return (
    <div className="space-y-8">
      <form onSubmit={submit} className="space-y-8">
        {(["ability", "willingness"] as const).map((dim) => (
          <section key={dim} className="sv-panel space-y-5" aria-labelledby={`q-${dim}`}>
            <div>
              <h2 id={`q-${dim}`} className="t-h3">
                {x[dim]}
              </h2>
              <p className="t-small text-muted">{dim === "ability" ? x.abilityHint : x.willingnessHint}</p>
            </div>
            {QUESTIONS.filter((q) => q.dimension === dim).map((q) => (
              <fieldset key={q.id} className="space-y-2">
                <legend className="font-semibold">{q[lang]}</legend>
                <div className="grid gap-1.5">
                  {q.options.map((o, i) => (
                    <label key={o.vi} className="flex items-start gap-2 t-small">
                      <input
                        type="radio"
                        name={q.id}
                        value={i + 1}
                        checked={answers[q.id] === i + 1}
                        onChange={() => setAnswers({ ...answers, [q.id]: i + 1 })}
                        className="mt-1"
                      />
                      {o[lang]}
                    </label>
                  ))}
                </div>
              </fieldset>
            ))}
          </section>
        ))}
        <div className="flex flex-wrap items-center gap-3">
          <button type="submit" className="sv-btn sv-btn--primary">
            {x.submit}
          </button>
          {missing ? <p className="t-small text-danger">{x.missing}</p> : null}
        </div>
      </form>

      {result ? (
        <section aria-live="polite" aria-labelledby="quiz-result" className="sv-panel space-y-4">
          <h2 id="quiz-result" className="t-h2">
            {x.result}
          </h2>
          <dl className="grid gap-2 sm:grid-cols-2">
            <div>
              <dt className="t-small text-muted">{x.ability}</dt>
              <dd className="font-semibold">{x.levels[result.ability]}</dd>
            </div>
            <div>
              <dt className="t-small text-muted">{x.willingness}</dt>
              <dd className="font-semibold">{x.levels[result.willingness]}</dd>
            </div>
          </dl>
          {suggested ? (
            <div className="space-y-1">
              <p className="t-small text-muted">{x.suggested}</p>
              <p className="t-h3">{suggested.name}</p>
              <p className="t-small">{suggested.summary}</p>
            </div>
          ) : null}
          <p className="t-small text-muted">{x.why}</p>
          {result.notes.length ? (
            <ul className="space-y-2">
              {result.notes.map((n) => (
                <li key={n} className="sv-note">
                  {x.notes[n]}
                </li>
              ))}
            </ul>
          ) : null}
          <p className="flex flex-wrap gap-4">
            {suggested ? <Link href={`${href(lang, "/muc-tieu")}?p=${suggested.id}`}>{x.goal}</Link> : null}
            <Link href={`${href(lang, "/phan-bo-theo-muc-tieu")}?level=${result.level}`}>{x.split}</Link>
            <Link href={href(lang, "/danh-muc-mau")}>{x.all}</Link>
          </p>
        </section>
      ) : null}
      <p className="t-small text-muted">{x.note}</p>
    </div>
  );
}
