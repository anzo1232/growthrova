import type { NextApiRequest, NextApiResponse } from "next";

import { loadLedgerLaneExample } from "@/server/ledger-lane-example";

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ error: "Method not allowed" });
  }

  try {
    const example = await loadLedgerLaneExample();
    res.setHeader("Cache-Control", "public, max-age=60, stale-while-revalidate=300");
    return res.status(200).json(example);
  } catch {
    return res.status(503).json({ error: "Example campaign unavailable" });
  }
}
