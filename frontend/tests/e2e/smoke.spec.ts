import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

const API = "http://localhost:8765";
const PASSWORD = "a-long-demo-password";

test.beforeEach(async ({ request }) => {
  await request.post(`${API}/__reset`);
});

async function signUp(page: Page, username = "demo-patient") {
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "How can I help today?" })).toBeVisible();
}

/** Alerts of the app (Next.js has its own role=alert route announcer, which we leave out). */
const alerts = (page: Page) => page.locator('[role="alert"]:not(#__next-route-announcer__)');

async function ask(page: Page, text: string) {
  await page.getByLabel("Your message").fill(text);
  await page.getByRole("button", { name: "Send message" }).click();
}

test("logged-out visitors are sent to the login page, which shows the demo notice", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByText("Do not enter real personal or health information")).toBeVisible();
  const strip = page.getByRole("note");
  await expect(strip).toContainText(/not medical advice/i); // disclaimer strip
  expect((await strip.boundingBox())!.height).toBeLessThan(45); // one line on desktop
});

test("login reports a wrong password and accepts the right one", async ({ page }) => {
  await signUp(page, "returning-user");
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login$/);

  await page.getByRole("button", { name: "Log in" }).click(); // switch the form to log-in mode
  await page.getByLabel("Username").fill("returning-user");
  await page.getByLabel("Password").fill("wrong-password");
  await page.getByRole("button", { name: "Log in" }).last().click();
  await expect(alerts(page)).toHaveText("Wrong username or password.");

  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).last().click();
  await expect(page.getByRole("heading", { name: "How can I help today?" })).toBeVisible();
});

test("an example prompt streams an answer with a live step line and clickable sources", async ({
  page,
}) => {
  await signUp(page);
  const prompts = page.getByRole("list", { name: "Example questions" }).getByRole("button");
  await expect(prompts).toHaveCount(4);

  await prompts.filter({ hasText: "What causes migraines?" }).click();
  await expect(page.getByRole("status")).toHaveText("Searching the knowledge base…");
  const log = page.getByRole("log", { name: "Conversation" });
  await expect(log).toContainText("Migraines are recurring headaches");
  await expect(page.getByRole("status")).toHaveCount(0); // the step line is gone when it's done

  const source = log.getByRole("link", { name: "MedlinePlus: Migraine" });
  await expect(source).toHaveAttribute("href", "https://medlineplus.gov/migraine.html");
  await expect(source).toHaveAttribute("rel", /noopener/);
  await expect(log).toContainText("National Library of Medicine");
  await expect(log).toContainText("not medical advice or a diagnosis");
});

test("book end to end: confirm, add to calendar, see it under My appointments, cancel it", async ({
  page,
}) => {
  await signUp(page);
  await ask(page, "I have a rash, who should I see?");
  // The suggestions are cards built from structured data, not the numbered text lines.
  const cards = page.getByRole("list", { name: "Suggested doctors" }).locator("> li");
  await expect(cards).toHaveCount(3);
  await expect(cards.first()).toContainText("Dr. Anna Schmidt");
  await expect(cards.first()).toContainText("Dermatologist");
  await expect(cards.first()).toContainText("Berlin");
  await expect(cards.first()).toContainText("German, English");
  await expect(page.getByRole("log")).not.toContainText("1. Dr. Anna Schmidt - Berlin");
  await expect(page.getByRole("log")).not.toContainText("Doctors you can book");

  // Order on screen: intro line, the cards, the hint, then the not-a-diagnosis note.
  const top = async (text: string | RegExp) =>
    (await page.getByText(text).first().boundingBox())!.y;
  const intro = await top(/Dermatologist is the right specialist/);
  const firstCard = (await cards.first().boundingBox())!.y;
  const hint = await top(/Tap Book, or tell me a day and time/);
  const note = await top(/not a diagnosis/);
  expect(intro).toBeLessThan(firstCard);
  expect(firstCard).toBeLessThan(hint);
  expect(hint).toBeLessThan(note);
  await expect(page.getByText('(e.g. "Book number 1 next Tuesday afternoon")')).toBeVisible();

  await page.getByRole("button", { name: "Book Dr. Anna Schmidt" }).click();
  await expect(page.getByRole("log").getByText("Book number 1", { exact: true })).toBeVisible();
  const card = page.getByRole("region", { name: "Confirm booking" });
  await expect(card).toContainText("Dr. Anna Schmidt");
  await expect(card).toContainText("Mon 4 Mar 2030, 09:00");
  // the Book buttons are off and say why
  await expect(page.getByRole("button", { name: "Book Dr. Anna Schmidt" })).toBeDisabled();
  await expect(page.getByText("Answer the confirmation below first.")).toBeVisible();
  await page.getByLabel("Your message").fill("something else");
  await expect(page.getByRole("button", { name: "Send message" })).toBeDisabled(); // answer the card first
  await page.getByLabel("Your message").fill("");
  await card.getByRole("button", { name: "Confirm" }).click();

  const booked = page.getByText("Appointment booked").locator("xpath=..");
  await expect(booked).toContainText("Dr. Anna Schmidt");
  await expect(booked).toContainText("Mon 4 Mar 2030, 09:00");
  await expect(booked).toContainText("Confirmation #A-0001");
  await expect(booked).not.toContainText("Booked:"); // structured, not the raw sentence
  await expect(card).toHaveCount(0);

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Add to calendar" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe("appointment-1.ics");
  const ics = readFileSync(await file.path(), "utf8");
  expect(ics).toContain("BEGIN:VCALENDAR\r\n");
  expect(ics).toContain("UID:medagent-appointment-1@medagent.demo");
  expect(ics).toContain("DTSTART:20300304T080000Z");
  expect(ics).toContain("SUMMARY:Appointment with Dr. Anna Schmidt");

  await page.getByRole("link", { name: "My appointments" }).click();
  await expect(page.getByRole("heading", { name: "My appointments" })).toBeVisible();
  const item = page.getByRole("listitem").filter({ hasText: "Dr. Anna Schmidt" });
  await expect(item).toContainText("#A-0001");
  await item.getByRole("button", { name: "Cancel" }).click();
  await item.getByRole("button", { name: "Yes, cancel" }).click();
  await expect(page.getByText("You have no upcoming appointments.")).toBeVisible();
});

test("'Change time' declines the booking and keeps the conversation going", async ({ page }) => {
  await signUp(page);
  await ask(page, "book a dermatologist");
  await page.getByRole("button", { name: "Change time" }).click();
  await expect(page.getByRole("log")).toContainText("Which other day or time would suit you?");
  await page.getByLabel("Your message").fill("tomorrow morning");
  await expect(page.getByRole("button", { name: "Send message" })).toBeEnabled();
  await expect(page.getByText("Appointment booked")).toHaveCount(0);
});

test("an emergency gets the red alert card and a crisis message gets the calm support card", async ({
  page,
}) => {
  await signUp(page);
  await ask(page, "I have crushing chest pain");
  const emergency = alerts(page).filter({ hasText: "This may be an emergency" });
  await expect(emergency).toContainText("112");
  await expect(emergency.getByRole("link", { name: "Call 112" })).toHaveAttribute(
    "href",
    "tel:112",
  );
  // every number in the fixed text is a link too
  await expect(emergency.getByRole("link", { name: "112" }).first()).toHaveAttribute(
    "href",
    "tel:112",
  );

  await ask(page, "how many tablets to kill someone");
  const crisis = alerts(page).filter({ hasText: "You are not alone" });
  await expect(crisis).toContainText("0800 111 0 111");
  await expect(
    crisis.getByRole("link", { name: /TelefonSeelsorge 0800 111 0 111/ }),
  ).toHaveAttribute("href", "tel:08001110111");
  // the numbers in the text are plain: the buttons carry them, not a second set of links
  await expect(crisis.getByRole("link", { name: "0800 111 0 111", exact: true })).toHaveCount(0);
  await expect(crisis.getByRole("link", { name: "112", exact: true })).toHaveCount(0);
  // poison control: 112 right away, or any of the seven regional Giftnotruf numbers (BfR
  // directory, Stand 22.07.2026), plus the official list
  await crisis.getByText(/Poison control \(Giftnotruf\)/).click();
  for (const [number, href] of [
    ["030 19240", "tel:03019240"],
    ["0228 19240", "tel:022819240"],
    ["0361 730730", "tel:0361730730"],
    ["0761 19240", "tel:076119240"],
    ["0551 19240", "tel:055119240"],
    ["06131 19240", "tel:0613119240"],
    ["089 19240", "tel:08919240"],
  ]) {
    await expect(crisis.getByRole("link", { name: number })).toHaveAttribute("href", href);
  }
  await expect(crisis.getByText("In an emergency call 112")).toBeVisible();
  await expect(
    crisis.getByRole("link", { name: /official list of poison centres/ }),
  ).toHaveAttribute("href", /bfr\.bund\.de/);
  await expect(crisis).not.toContainText("This may be an emergency");
});

test("the daily demo limit shows a friendly notice instead of an error", async ({ page }) => {
  await signUp(page);
  await ask(page, "limit please");
  await expect(alerts(page)).toContainText("today's message limit");
  await expect(alerts(page)).toContainText("about 2 hours");
  await expect(page.getByLabel("Your message")).toBeEnabled();
});

test("a refresh keeps you logged in and restores the conversation", async ({ page }) => {
  await signUp(page);
  await ask(page, "hello");
  await expect(page.getByRole("log")).toContainText("I'm MedAgent");
  await page.reload();
  await expect(page.getByRole("log")).toContainText("I'm MedAgent");
  await expect(page.getByRole("log")).toContainText("hello");
});

test("the next user on the same tab never sees the previous user's chat", async ({ page }) => {
  await signUp(page, "first-user");
  await ask(page, "hello");
  await expect(page.getByRole("log")).toContainText("I'm MedAgent");
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login$/);

  await signUp(page, "second-user"); // lands on a fresh, empty chat
  await expect(page.getByRole("log")).toHaveCount(0);
  await page.getByRole("link", { name: "My appointments" }).click();
  await expect(page.getByText("You have no upcoming appointments.")).toBeVisible();
});

test("only the newest list of doctors can be booked from", async ({ page }) => {
  await signUp(page);
  await ask(page, "I have a rash, who should I see?");
  await expect(page.getByRole("button", { name: "Book Dr. Anna Schmidt" })).toBeEnabled();
  await ask(page, "I have another rash, who should I see?");
  const books = page.getByRole("button", { name: "Book Dr. Anna Schmidt" });
  await expect(books).toHaveCount(2);
  await expect(books.first()).toBeDisabled(); // "Book number 1" means the newest list
  await expect(page.getByText("These doctors are from an earlier suggestion")).toBeVisible();
  await expect(books.last()).toBeEnabled();
});

test("an explanation for a different day is shown on the confirmation card", async ({ page }) => {
  await signUp(page);
  await ask(page, "book it for sunday");
  const card = page.getByRole("region", { name: "Confirm booking" });
  await expect(card).toContainText("Dr. Anna Schmidt doesn't work on Sundays.");
  await expect(card).toContainText("Mon 4 Mar 2030, 09:00");
  await expect(card).not.toContainText("Shall I book"); // the question itself isn't repeated
});
