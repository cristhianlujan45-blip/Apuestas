"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { bankrollNow, suggestedStake } from "@/lib/bankroll";
import { cop } from "@/lib/format";

/** Importe sugerido por la banca del usuario (Kelly fraccional con tope). */
export default function StakeHint({ p, odds }: { p: number; odds: number }) {
  const [bank, setBank] = useState(0);
  useEffect(() => setBank(bankrollNow()), []);
  if (!bank) return <Link href="/configuracion" className="text-[11px] text-ink-muted underline">configurar banca</Link>;
  const st = suggestedStake(p, odds, bank);
  return <span className="text-[11px] text-ink-2 num">{st ? `sugerido ${cop(st)}` : "sin ventaja: no apostar"}</span>;
}
