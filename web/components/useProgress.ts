"use client";

import { useSyncExternalStore } from "react";

// Progress kept only in this browser (lessons learnt, planning steps visited). Nothing is sent anywhere.
const listeners = new Set<() => void>();
const cache = new Map<string, string[]>();

function read(key: string): string[] {
  if (!cache.has(key)) {
    let value: string[] = [];
    try {
      const raw = JSON.parse(window.localStorage.getItem(key) ?? "[]");
      value = Array.isArray(raw) ? raw.filter((x): x is string => typeof x === "string").slice(0, 50) : [];
    } catch {
      value = [];
    }
    cache.set(key, value);
  }
  return cache.get(key) as string[];
}

const EMPTY: string[] = [];

export function useProgress(key: string) {
  const done = useSyncExternalStore(
    (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    () => read(key),
    () => EMPTY,
  );
  const set = (id: string, on: boolean) => {
    const next = on ? [...new Set([...read(key), id])] : read(key).filter((x) => x !== id);
    cache.set(key, next);
    try {
      window.localStorage.setItem(key, JSON.stringify(next));
    } catch {
      // storage blocked: progress lasts for this visit only
    }
    listeners.forEach((fn) => fn());
  };
  return { done, set };
}

export const LEARN_KEY = "soivi.learn.v1";
export const JOURNEY_KEY = "soivi.journey.v1";
