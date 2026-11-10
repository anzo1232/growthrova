import { createHash } from "node:crypto";
import { join } from "node:path";
import { readFile } from "node:fs/promises";

export const LEDGER_LANE_CAMPAIGN_ID = "8c9cf54e5728446ca7706e9b813db893";
export const LEDGER_LANE_ASSET_SHA256 = "f26f2322940c9d8c6430628a5dc495aabd47b32d9d93ad2d65caa492ecb4f317";

const DEFAULT_RECEIPT =
  join(process.cwd(), "server/data/ledger-lane-receipt.json");
const DEFAULT_ASSET =
  join(process.cwd(), "server/data/ledger-lane.jpg");

export type LedgerLaneExample = {
  exampleId: "ledger-lane";
  readOnly: true;
  campaign: {
    name: string;
    goal: string;
    assetCount: number;
  };
  brand: {
    name: string;
    website: string;
    description: string;
    colours: [string, string];
    fontStyle: string;
  };
  metaCreative: {
    assetUrl: string;
    aspectRatio: "1792 / 2400";
    headline: string;
    supportingLine: string;
    callToAction: string;
    status: "Draft";
  };
  social: {
    channel: string;
    caption: string;
    status: "Draft";
  };
};

type ReceiptAdvert = {
  business?: string;
  campaignId?: string;
  fileName?: string;
  sha256?: string;
  originalBytesVerified?: boolean;
  sourceCopy?: {
    channel?: string;
    copyDraft?: string;
    graphicText?: string;
    supportingLine?: string;
    callToAction?: string;
    status?: string;
  };
  reviewResponse?: {
    sourceContext?: {
      sourceUrl?: string;
      goal?: string;
      brandKit?: {
        name?: string;
        primary_color?: string;
        secondary_color?: string;
        font_style?: string;
      };
    };
  };
};

async function selectedAdvert(): Promise<ReceiptAdvert> {
  const receiptPath = process.env.GROWTHROVA_LEDGER_LANE_RECEIPT || DEFAULT_RECEIPT;
  const receipt = JSON.parse(await readFile(receiptPath, "utf8")) as {
    selectedAdverts?: ReceiptAdvert[];
  };
  const advert = receipt.selectedAdverts?.find((candidate) => candidate.business === "Ledger Lane");
  if (
    !advert ||
    advert.campaignId !== LEDGER_LANE_CAMPAIGN_ID ||
    advert.fileName !== "ledger-lane-photographic-v5.jpg" ||
    advert.originalBytesVerified !== true
  ) {
    throw new Error("Unexpected Ledger Lane campaign record");
  }
  return advert;
}

export async function loadLedgerLaneAsset(): Promise<Buffer> {
  const advert = await selectedAdvert();
  const assetPath = process.env.GROWTHROVA_LEDGER_LANE_ASSET || DEFAULT_ASSET;
  const bytes = await readFile(assetPath);
  const sha256 = createHash("sha256").update(bytes).digest("hex");
  if (sha256 !== advert.sha256) {
    throw new Error("Ledger Lane asset hash mismatch");
  }
  return bytes;
}

export async function loadLedgerLaneExample(): Promise<LedgerLaneExample> {
  const advert = await selectedAdvert();
  const copy = advert.sourceCopy;
  const context = advert.reviewResponse?.sourceContext;
  const brand = context?.brandKit;
  if (
    !copy?.copyDraft ||
    !copy.graphicText ||
    !copy.supportingLine ||
    !copy.callToAction ||
    !copy.channel ||
    !context?.sourceUrl ||
    !context.goal ||
    !brand?.name ||
    !brand.primary_color ||
    !brand.secondary_color ||
    !brand.font_style ||
    advert.sha256 !== LEDGER_LANE_ASSET_SHA256
  ) {
    throw new Error("Ledger Lane public example is incomplete");
  }

  return {
    exampleId: "ledger-lane",
    readOnly: true,
    campaign: {
      name: "Ledger Lane — website showcase",
      goal: context.goal,
      assetCount: 2,
    },
    brand: {
      name: brand.name,
      website: context.sourceUrl,
      description: copy.supportingLine,
      colours: [brand.primary_color, brand.secondary_color],
      fontStyle: brand.font_style,
    },
    metaCreative: {
      assetUrl: "/api/examples/ledger-lane/creative",
      aspectRatio: "1792 / 2400",
      headline: copy.graphicText,
      supportingLine: copy.supportingLine,
      callToAction: copy.callToAction,
      status: "Draft",
    },
    social: {
      channel: copy.channel,
      caption: copy.copyDraft,
      status: "Draft",
    },
  };
}
