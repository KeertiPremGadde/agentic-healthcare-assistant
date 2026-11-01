import { HeartHandshake, Phone, ShieldAlert } from "lucide-react";
import { linkifyPhones } from "@/lib/phone";
import { Notice } from "./notice";

const callButton =
  "inline-flex h-11 items-center justify-center gap-2 rounded-xl px-5 text-sm font-semibold " +
  "transition-colors focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none";
const textLink = "font-semibold underline underline-offset-2";

/** The fixed reply text with every known phone number as a tel: link. */
function PhoneText({ text }: { text: string }) {
  return (
    <p className="mt-1.5 leading-relaxed whitespace-pre-wrap">
      {linkifyPhones(text).map((part, i) =>
        part.tel ? (
          <a key={i} href={`tel:${part.tel}`} className={textLink}>
            {part.text}
          </a>
        ) : (
          part.text
        ),
      )}
    </p>
  );
}

/** Acute emergency: the one place red is used. role=alert so screen readers announce it. */
export function EmergencyCard({ text }: { text: string }) {
  return (
    <div role="alert" className="flex">
      <Notice tone="danger" icon={ShieldAlert} title="This may be an emergency">
        <PhoneText text={text} />
        <a href="tel:112" className={`${callButton} mt-3 bg-red-700 text-white hover:bg-red-800`}>
          <Phone className="size-4" aria-hidden />
          Call 112
        </a>
      </Notice>
    </div>
  );
}

// Poison information centres (Giftnotruf). Source: the official directory of the Federal Institute
// for Risk Assessment (BfR), "Giftinformationszentren in Deutschland", marked "Stand: 22.07.2026",
// emergency lines (Notruf) read from that page on 2026-11-01. Germany has several regional centres
// and no single number, so only numbers confirmed there are shown; every other region is sent to
// the official directory. Re-check against the directory before adding or changing a number.
const POISON_CENTRES = [
  { city: "Berlin", label: "030 19240" },
  { city: "München", label: "089 19240" },
];
const POISON_DIRECTORY =
  "https://www.bfr.bund.de/deutsches-produktregister-de-pro/giftinformationszentren-in-deutschland/";

const tel = (label: string) => `tel:${label.replace(/\s/g, "")}`;

/** Self-harm or harm to others: calm and supportive, not an alarm. Numbers are one tap away. */
export function CrisisCard({ text }: { text: string }) {
  return (
    <div role="alert" className="flex">
      <Notice tone="care" icon={HeartHandshake} title="You are not alone">
        {/* plain text here: the call buttons below carry the numbers, so no second set of links */}
        <p className="mt-1.5 leading-relaxed whitespace-pre-wrap">{text}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <a href="tel:08001110111" className={`${callButton} bg-care-foreground text-care`}>
            <Phone className="size-4" aria-hidden />
            TelefonSeelsorge 0800 111 0 111
          </a>
          <a
            href="tel:112"
            className={`${callButton} border-care-border bg-card text-care-foreground border`}
          >
            <Phone className="size-4" aria-hidden />
            Call 112
          </a>
        </div>
        <details className="border-care-border bg-card/60 mt-3 rounded-xl border px-3 py-2">
          <summary className="focus-visible:ring-ring/50 cursor-pointer font-medium focus-visible:ring-3 focus-visible:outline-none">
            Someone swallowed something harmful? Poison control (Giftnotruf)
          </summary>
          <div className="mt-2 space-y-2 text-sm">
            <p>
              In an emergency call{" "}
              <a href="tel:112" className={textLink}>
                112
              </a>{" "}
              right away. For advice you can also call a poison centre:
            </p>
            <ul className="grid gap-x-4 gap-y-1 sm:grid-cols-2">
              {POISON_CENTRES.map((centre) => (
                <li key={centre.city}>
                  {centre.city}:{" "}
                  <a href={tel(centre.label)} className={textLink}>
                    {centre.label}
                  </a>
                </li>
              ))}
            </ul>
            <p>
              Other regions: see the{" "}
              <a
                href={POISON_DIRECTORY}
                target="_blank"
                rel="noopener noreferrer"
                className={textLink}
              >
                official list of poison centres (BfR)
              </a>
              . In the US:{" "}
              <a href="tel:18002221222" className={textLink}>
                Poison Help 1-800-222-1222
              </a>
              .
            </p>
          </div>
        </details>
      </Notice>
    </div>
  );
}
