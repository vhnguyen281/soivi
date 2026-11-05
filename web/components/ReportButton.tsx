"use client";

import { useEffect, useId, useRef, useState } from "react";

import { Icon } from "./ui";

type Labels = {
  button: string;
  title: string;
  intro: string;
  message: string;
  screenshot: string;
  contact: string;
  send: string;
  cancel: string;
  sending: string;
  thanks: string;
  error: string;
  tooMany: string;
};

const SITE_KEY = process.env.NEXT_PUBLIC_CAPTCHA_SITE_KEY ?? "";

/**
 * "Báo sai số liệu": a native <dialog> (focus trapping and Esc for free) that posts
 * a community report. Reports never change a value; they ask for a re-check.
 */
export function ReportButton({
  labels,
  institution,
  productRef,
}: {
  labels: Labels;
  institution?: string;
  productRef?: string;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [state, setState] = useState<"idle" | "sending" | "done" | "error" | "limited">("idle");
  // The form is only put in the page once someone opens it: pages with many
  // tables stay light, and nothing is sent until the visitor asks.
  const [opened, setOpened] = useState(false);
  const id = useId();

  useEffect(() => {
    if (opened && !dialog.current?.open) dialog.current?.showModal();
  }, [opened]);

  function open() {
    setState("idle");
    if (SITE_KEY && !document.getElementById("cf-turnstile")) {
      const s = document.createElement("script");
      s.id = "cf-turnstile";
      s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js";
      s.async = true;
      document.head.appendChild(s);
    }
    if (opened) dialog.current?.showModal();
    else setOpened(true);
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const token = form.get("cf-turnstile-response");
    if (token) form.set("captcha_token", String(token));
    form.delete("cf-turnstile-response");
    const file = form.get("screenshot");
    if (file instanceof File && !file.size) form.delete("screenshot");
    setState("sending");
    try {
      const res = await fetch("/api/reports", { method: "POST", body: form });
      setState(res.ok ? "done" : res.status === 429 ? "limited" : "error");
    } catch {
      setState("error");
    }
  }

  return (
    <>
      <button type="button" onClick={open} className="sv-btn sv-btn--ghost sv-btn--sm">
        <Icon name="alert" />
        {labels.button}
      </button>
      {opened ? (
      <dialog
        ref={dialog}
        aria-labelledby={`${id}-title`}
        className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-[16px] border border-line bg-surface-raised p-0 text-ink shadow-pop backdrop:bg-black/50"
      >
        <form onSubmit={submit} className="space-y-4 p-6">
          <h2 id={`${id}-title`} className="t-h3">
            {labels.title}
          </h2>
          <p className="t-small text-muted">{labels.intro}</p>
          {institution ? <input type="hidden" name="institution" value={institution} /> : null}
          {productRef ? <input type="hidden" name="product_ref" value={productRef} /> : null}
          <label className="sv-field">
            {labels.message}
            <textarea
              name="message"
              required
              minLength={10}
              maxLength={2000}
              rows={4}
              className="sv-input py-2"
            />
          </label>
          <label className="sv-field">
            {labels.screenshot}
            <input
              type="file"
              name="screenshot"
              accept="image/png,image/jpeg,image/webp"
              className="t-small font-normal"
            />
          </label>
          <label className="sv-field">
            {labels.contact}
            <input type="text" name="contact" maxLength={200} autoComplete="email" />
          </label>
          {SITE_KEY ? <div className="cf-turnstile" data-sitekey={SITE_KEY} /> : null}
          <p role="status" aria-live="polite" className="t-small">
            {state === "sending" && labels.sending}
            {state === "done" && labels.thanks}
            {state === "error" && labels.error}
            {state === "limited" && labels.tooMany}
          </p>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => dialog.current?.close()}
              className="sv-btn sv-btn--secondary sv-btn--sm"
            >
              {labels.cancel}
            </button>
            <button
              type="submit"
              disabled={state === "sending" || state === "done"}
              className="sv-btn sv-btn--primary sv-btn--sm"
            >
              {labels.send}
            </button>
          </div>
        </form>
      </dialog>
      ) : null}
    </>
  );
}
