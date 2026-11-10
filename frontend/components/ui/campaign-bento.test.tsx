// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { LedgerLaneExample } from "@/server/ledger-lane-example";
import CampaignBento from "./campaign-bento";

const example: LedgerLaneExample = {
  exampleId: "ledger-lane",
  readOnly: true,
  campaign: { name: "Ledger Lane — website showcase", goal: "enquiries", assetCount: 2 },
  brand: {
    name: "Ledger Lane",
    website: "https://example.org/",
    description: "Bookkeeping for small businesses.",
    colours: ["#103e2e", "#f5f0e6"],
    fontStyle: "classic",
  },
  metaCreative: {
    assetUrl: "/api/examples/ledger-lane/creative",
    aspectRatio: "1792 / 2400",
    headline: "Less paperwork. More headspace.",
    supportingLine: "Bookkeeping for small businesses.",
    callToAction: "Book a consultation.",
    status: "Draft",
  },
  social: {
    channel: "Instagram",
    caption:
      "Less paperwork. More headspace. Ledger Lane is a fictional bookkeeping business offering bookkeeping for small businesses. Book a consultation.",
    status: "Draft",
  },
};

afterEach(cleanup);

describe("CampaignBento", () => {
  it("renders the saved Ledger Lane outputs and no invented channels", () => {
    render(<CampaignBento initialExample={example} />);

    expect(screen.getAllByText("Ledger Lane").length).toBeGreaterThan(0);
    expect(screen.getByText("https://example.org/")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Ledger Lane advert/i })).toHaveAttribute(
      "src",
      "/api/examples/ledger-lane/creative",
    );
    expect(screen.getAllByText("Less paperwork. More headspace.").length).toBeGreaterThan(0);
    expect(screen.getByText("Book a consultation.")).toBeInTheDocument();
    expect(screen.getByText("Read-only example")).toBeInTheDocument();
    expect(screen.queryByText(/Northstar Coffee/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Email campaigns/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Email$/i)).not.toBeInTheDocument();
  });

  it("keeps the original creative at its saved aspect ratio", () => {
    render(<CampaignBento initialExample={example} />);
    expect(screen.getByTestId("ledger-lane-creative")).toHaveStyle({ aspectRatio: "1792 / 2400" });
  });
});
