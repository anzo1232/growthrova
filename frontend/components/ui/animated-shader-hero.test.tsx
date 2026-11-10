import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import Hero from "./animated-shader-hero";
import HeroDemo from "../demo";
import { loadLedgerLaneExample } from "@/server/ledger-lane-example";

describe("Animated Shader Hero", () => {
  it("renders the consumer-provided trust badge, headline, subtitle, and calls to action", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    let html = "";
    try {
      html = renderToStaticMarkup(
        <Hero
          trustBadge={{ text: "Trusted teams", icons: ["✨"] }}
          headline={{ line1: "First line", line2: "Second line" }}
          subtitle="A supplied subtitle"
          buttons={{
            primary: { text: "Primary action" },
            secondary: { text: "Secondary action" },
          }}
        />,
      );
    } finally {
      consoleError.mockRestore();
    }

    expect(html).toContain("Trusted teams");
    expect(html).toContain("First line");
    expect(html).toContain("Second line");
    expect(html).toContain("A supplied subtitle");
    expect(html).toContain("Primary action");
    expect(html).toContain("Secondary action");
    expect(html).toContain("<canvas");
  });

  it("renders the Growthrova hero message and campaign actions", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    let html = "";
    try {
      html = renderToStaticMarkup(<HeroDemo />);
    } finally {
      consoleError.mockRestore();
    }

    expect(html).toContain("growthrova");
    expect(html).toContain("Your marketing team,");
    expect(html).toContain("built in.");
    expect(html).toContain("Enter your website to create Meta ads, social posts, and emails tailored to your business.");
    expect(html).toContain("Create a Campaign");
    expect(html).toContain("See Example Campaigns");
    expect(html).not.toContain("Trusted by forward-thinking teams.");
    expect(html).not.toContain("Workflow Into Orbit");
  });

  it("continues from the hero into the saved Ledger Lane example campaign", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    let html = "";
    try {
      html = renderToStaticMarkup(<HeroDemo initialExample={await loadLedgerLaneExample()} />);
    } finally {
      consoleError.mockRestore();
    }

    expect(html).toContain("From your website to your next campaign");
    expect(html).toContain("Start with your website");
    expect(html).toContain("Meta creative");
    expect(html).toContain("Social post");
    expect(html).toContain("Campaign workspace");
    expect(html.match(/Ledger Lane/g)?.length).toBeGreaterThanOrEqual(4);
    expect(html.match(/Draft/g)?.length).toBeGreaterThanOrEqual(2);
    expect(html).not.toContain("Northstar Coffee");
    expect(html).not.toContain("Email campaigns");
    expect(html).not.toContain("How to Use the Hero Component");
    expect(html).not.toContain("Server latency");
    expect(html).not.toContain("Lighthouse");
    expect(html).not.toContain("Tech stack");
  });
});
