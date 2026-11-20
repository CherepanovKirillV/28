import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, getHealth, getRoot, runCase } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("backend API", () => {
  it.each([
    ["root", getRoot, "/"],
    ["health", getHealth, "/health"],
  ])("calls %s endpoint", async (_, call, path) => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ team: "team28", status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(call()).resolves.toEqual({ team: "team28", status: "ok" });
    expect(fetchMock).toHaveBeenCalledWith(
      path,
      expect.objectContaining({ headers: expect.objectContaining({ Accept: "application/json" }) }),
    );
  });

  it("sends run payload and authorization", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ weeks: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      runCase({ case: 3, dataset_code: "case3-dev-v1" }, "Bearer token"),
    ).resolves.toEqual({ weeks: [] });
    expect(fetchMock).toHaveBeenCalledWith(
      "/run",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ case: 3, dataset_code: "case3-dev-v1" }),
        headers: expect.objectContaining({
          Authorization: "Bearer token",
          "Content-Type": "application/json",
        }),
      }),
    );
  });

  it("can request /run without a browser token for server-side authentication", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ weeks: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await runCase({ case: 3, dataset_code: "case3-dev-v1" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/run",
      expect.objectContaining({
        headers: expect.not.objectContaining({ Authorization: expect.anything() }),
      }),
    );
  });

  it("throws ApiError with response details", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Missing Authorization" }), {
          status: 400,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const error = await runCase({ case: 3, dataset_code: "dataset" }, "").catch(
      (reason: unknown) => reason,
    );

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 400, body: { detail: "Missing Authorization" } });
  });
});

