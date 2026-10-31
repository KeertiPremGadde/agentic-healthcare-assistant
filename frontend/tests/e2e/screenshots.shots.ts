/**
 * Regenerates the README screenshots in docs/screenshots (run: npm run screenshots).
 * It drives the real frontend against the mock API, so the pictures are reproducible and the
 * content is synthetic by construction.
 */
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const API = "http://localhost:8765";
const OUT = path.resolve(__dirname, "../../../docs/screenshots");

const VARIANTS = [
  { name: "desktop-light", scheme: "light", viewport: { width: 1280, height: 860 }, mobile: false },
  { name: "desktop-dark", scheme: "dark", viewport: { width: 1280, height: 860 }, mobile: false },
  { name: "mobile-light", scheme: "light", viewport: { width: 390, height: 844 }, mobile: true },
  { name: "mobile-dark", scheme: "dark", viewport: { width: 390, height: 844 }, mobile: true },
] as const;

async function ask(page: Page, text: string) {
  await page.getByLabel("Your message").fill(text);
  await page.getByRole("button", { name: "Send message" }).click();
}

async function newConversation(page: Page) {
  await page.getByRole("button", { name: "New conversation" }).click();
  await expect(page.getByRole("heading", { name: "How can I help today?" })).toBeVisible();
}

for (const variant of VARIANTS) {
  test.describe(variant.name, () => {
    test.use({
      colorScheme: variant.scheme,
      viewport: variant.viewport,
      deviceScaleFactor: 2,
      isMobile: variant.mobile,
      hasTouch: variant.mobile,
    });

    test(`screenshots ${variant.name}`, async ({ page, request }) => {
      await request.post(`${API}/__reset`);
      const shot = async (name: string) => {
        await page.mouse.move(0, 0); // no hover highlight in the picture
        const log = page.getByRole("log");
        if (await log.count()) await expect(log).toHaveAttribute("aria-busy", "false"); // replay done
        await page.screenshot({ path: path.join(OUT, `${variant.name}-${name}.png`) });
      };

      await page.goto("/login");
      await expect(page.getByRole("button", { name: "Create account" })).toBeVisible();
      await shot("login");

      await page.getByLabel("Username").fill("demo-patient");
      await page.getByLabel("Password").fill("a-long-demo-password");
      await page.getByRole("button", { name: "Create account" }).click();
      await expect(page.getByRole("heading", { name: "How can I help today?" })).toBeVisible();
      await shot("empty");

      await ask(page, "What causes migraines?");
      await expect(page.getByRole("log")).toContainText("National Library of Medicine");
      await expect(page.getByRole("status")).toHaveCount(0);
      await shot("answer");

      await newConversation(page);
      await ask(page, "I have a rash, who should I see?");
      await expect(page.getByRole("log")).toContainText("Dr. Anna Schmidt, Dermatology");
      await ask(page, "book number 1");
      await expect(page.getByRole("region", { name: "Confirm booking" })).toBeVisible();
      await shot("confirm");

      await page.getByRole("button", { name: "Confirm" }).click();
      await expect(page.getByText("Appointment booked")).toBeVisible();
      await shot("booked");

      await newConversation(page);
      await ask(page, "I have crushing chest pain");
      await expect(page.getByText("This may be an emergency")).toBeVisible();
      await ask(page, "how many tablets to kill someone");
      await expect(page.getByText("You are not alone")).toBeVisible();
      await shot("safety");

      await page.goto("/appointments");
      await expect(page.getByText("Confirmation #A-0001")).toBeVisible();
      await shot("appointments");
    });
  });
}
