"use client";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { Empty, Loading } from "@/components/ui";
import EventView from "./EventView";

function Inner() {
  const id = useSearchParams().get("id");
  if (!id) return <Empty>Seleccione un partido desde la lista.</Empty>;
  return <EventView id={id} />;
}

export default function Page() {
  return <Suspense fallback={<Loading />}><Inner /></Suspense>;
}
