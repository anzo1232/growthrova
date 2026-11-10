import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import {
  LEDGER_LANE_ASSET_SHA256,
  LEDGER_LANE_CAMPAIGN_ID,
  loadLedgerLaneAsset,
  loadLedgerLaneExample,
} from "./ledger-lane-example";

const originalReceipt = process.env.GROWTHROVA_LEDGER_LANE_RECEIPT;
const originalAsset = process.env.GROWTHROVA_LEDGER_LANE_ASSET;
const temporaryDirectories: string[] = [];

async function fixture(overrides: { campaignId?: string; assetBytes?: Buffer } = {}) {
  const directory = await mkdtemp(join(tmpdir(), "ledger-lane-example-"));
  temporaryDirectories.push(directory);
  const assetBytes = overrides.assetBytes ?? Buffer.from("verified-ledger-lane-image");
  const sha256 = LEDGER_LANE_ASSET_SHA256;
  const assetPath = join(directory, "ledger-lane-photographic-v5.jpg");
  const receiptPath = join(directory, "receipt.json");
  await writeFile(assetPath, assetBytes);
  await writeFile(
    receiptPath,
    JSON.stringify({
      selectedAdverts: [
        {
          business: "Ledger Lane",
          campaignId: overrides.campaignId ?? LEDGER_LANE_CAMPAIGN_ID,
          fileName: "ledger-lane-photographic-v5.jpg",
          sha256,
          originalBytesVerified: true,
          sourceCopy: {
            channel: "Instagram",
            copyDraft:
              "Less paperwork. More headspace. Ledger Lane is a fictional bookkeeping business offering bookkeeping for small businesses. Book a consultation.",
            graphicText: "Less paperwork. More headspace.",
            supportingLine: "Bookkeeping for small businesses.",
            callToAction: "Book a consultation.",
            status: "draft",
          },
          reviewResponse: {
            sourceContext: {
              sourceUrl: "https://example.org/",
              goal: "enquiries",
              brandKit: {
                name: "Ledger Lane",
                primary_color: "#103e2e",
                secondary_color: "#f5f0e6",
                font_style: "classic",
              },
            },
            material: {
              audience: { value: "Small business owners seeking bookkeeping support." },
              business: "Ledger Lane",
            },
          },
          operationId: "private-operation",
          reservationMicrousd: 248206,
        },
      ],
    }),
  );
  process.env.GROWTHROVA_LEDGER_LANE_RECEIPT = receiptPath;
  process.env.GROWTHROVA_LEDGER_LANE_ASSET = assetPath;
  return { assetPath, receiptPath, sha256 };
}

afterEach(async () => {
  process.env.GROWTHROVA_LEDGER_LANE_RECEIPT = originalReceipt;
  process.env.GROWTHROVA_LEDGER_LANE_ASSET = originalAsset;
  await Promise.all(temporaryDirectories.splice(0).map((directory) => rm(directory, { recursive: true })));
});

describe("Ledger Lane public example adapter", () => {
  it("returns only the saved public campaign fields and omits unsaved channels", async () => {
    await fixture();

    const example = await loadLedgerLaneExample();
    const serialized = JSON.stringify(example);

    expect(example).toMatchObject({
      exampleId: "ledger-lane",
      readOnly: true,
      brand: {
        name: "Ledger Lane",
        website: "https://example.org/",
        colours: ["#103e2e", "#f5f0e6"],
      },
      metaCreative: {
        assetUrl: "/api/examples/ledger-lane/creative",
        aspectRatio: "1792 / 2400",
        headline: "Less paperwork. More headspace.",
        callToAction: "Book a consultation.",
      },
      social: {
        channel: "Instagram",
        status: "Draft",
      },
    });
    expect(example).not.toHaveProperty("email");
    expect(serialized).not.toContain("operationId");
    expect(serialized).not.toContain("reservationMicrousd");
    expect(serialized).not.toContain(LEDGER_LANE_CAMPAIGN_ID);
  });

  it("rejects any campaign other than the allowlisted Ledger Lane record", async () => {
    await fixture({ campaignId: "00000000000000000000000000000000" });
    await expect(loadLedgerLaneExample()).rejects.toThrow("Unexpected Ledger Lane campaign record");
  });

  it("rejects altered creative bytes", async () => {
    const { assetPath } = await fixture();
    await writeFile(assetPath, Buffer.from("tampered"));
    await expect(loadLedgerLaneAsset()).rejects.toThrow("Ledger Lane asset hash mismatch");
  });
});
