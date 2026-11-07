import { Fraunces, Patrick_Hand } from "next/font/google";

// Fonts for the "treasure map" journey (homepage, planning hub, lessons). Self-hosted by Next at build.
export const fraunces = Fraunces({
  subsets: ["vietnamese", "latin"],
  weight: ["600", "900"],
  display: "swap",
  variable: "--font-fraunces",
});
export const hand = Patrick_Hand({
  subsets: ["vietnamese", "latin"],
  weight: "400",
  display: "swap",
  variable: "--font-hand",
});
export const mapFonts = `${fraunces.variable} ${hand.variable}`;
