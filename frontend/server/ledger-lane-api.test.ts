import type { NextApiRequest, NextApiResponse } from "next";
import { describe, expect, it } from "vitest";

import creativeHandler from "@/pages/api/examples/ledger-lane/creative";
import exampleHandler from "@/pages/api/examples/ledger-lane";

type CapturedResponse = {
  statusCode: number;
  headers: Record<string, string>;
  body: unknown;
};

function response(): { capture: CapturedResponse; value: NextApiResponse } {
  const capture: CapturedResponse = { statusCode: 200, headers: {}, body: undefined };
  const value = {
    status(code: number) {
      capture.statusCode = code;
      return this;
    },
    setHeader(name: string, headerValue: string) {
      capture.headers[name.toLowerCase()] = headerValue;
      return this;
    },
    json(body: unknown) {
      capture.body = body;
      return this;
    },
    send(body: unknown) {
      capture.body = body;
      return this;
    },
    end(body?: unknown) {
      capture.body = body;
      return this;
    },
  } as unknown as NextApiResponse;
  return { capture, value };
}

function request(method: string): NextApiRequest {
  return { method } as NextApiRequest;
}

describe("Ledger Lane public example API", () => {
  it("returns the allowlisted read-only campaign without backend-private fields", async () => {
    const { capture, value } = response();
    await exampleHandler(request("GET"), value);

    expect(capture.statusCode).toBe(200);
    expect(capture.headers["cache-control"]).toContain("public");
    expect(capture.body).toMatchObject({ exampleId: "ledger-lane", readOnly: true });
    const serialized = JSON.stringify(capture.body);
    expect(serialized).not.toMatch(/organisation|operationId|reservation|ownerApproved|campaignId/i);
  });

  it("rejects mutations", async () => {
    const { capture, value } = response();
    await exampleHandler(request("POST"), value);
    expect(capture.statusCode).toBe(405);
    expect(capture.headers.allow).toBe("GET");
  });

  it("streams the verified original JPEG with immutable caching", async () => {
    const { capture, value } = response();
    await creativeHandler(request("GET"), value);

    expect(capture.statusCode).toBe(200);
    expect(capture.headers["content-type"]).toBe("image/jpeg");
    expect(capture.headers["cache-control"]).toContain("immutable");
    expect(Buffer.isBuffer(capture.body)).toBe(true);
    expect((capture.body as Buffer).byteLength).toBeGreaterThan(100_000);
  });
});
