import type { NextApiRequest, NextApiResponse } from "next";

import { loadLedgerLaneAsset } from "@/server/ledger-lane-example";

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ error: "Method not allowed" });
  }

  try {
    const asset = await loadLedgerLaneAsset();
    res.setHeader("Content-Type", "image/jpeg");
    res.setHeader("Content-Length", String(asset.byteLength));
    res.setHeader("Cache-Control", "public, max-age=31536000, immutable");
    return res.status(200).send(asset);
  } catch {
    return res.status(404).json({ error: "Creative unavailable" });
  }
}
