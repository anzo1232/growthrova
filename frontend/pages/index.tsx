import type { GetServerSideProps, InferGetServerSidePropsType } from "next";

import HeroDemo from "@/components/demo";
import { loadLedgerLaneExample } from "@/server/ledger-lane-example";

export const getServerSideProps: GetServerSideProps = async () => ({
  props: { initialExample: await loadLedgerLaneExample() },
});

export default function Home({
  initialExample,
}: InferGetServerSidePropsType<typeof getServerSideProps>) {
  return <HeroDemo initialExample={initialExample} />;
}
