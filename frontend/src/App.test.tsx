import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./App";

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    initialToken: () => "secret",
    saveToken: vi.fn(),
    listJobs: vi.fn().mockResolvedValue({ jobs: [] }),
    createJob: vi.fn().mockResolvedValue({
      id: "job-1",
      status: "queued",
      path: "/tmp/demo",
      age_months: 6,
      include_duplicates: true,
      include_near_duplicates: true,
      created_at: "now",
      progress_phase: "queued",
      progress_percent: 0,
      progress_message: "Queued",
      confirmation_phrases: { clean: "CLEAN job-1", archive: "ARCHIVE job-1" }
    }),
    openJobEvents: vi.fn(() => ({ close: vi.fn(), addEventListener: vi.fn() }))
  };
});

test("starts a scan job from the dashboard", async () => {
  render(<App />);
  await userEvent.type(screen.getByLabelText(/Path/i), "/tmp/demo");
  await userEvent.click(screen.getByRole("button", { name: /Scan/i }));
  expect(await screen.findByText("/tmp/demo")).toBeInTheDocument();
});
