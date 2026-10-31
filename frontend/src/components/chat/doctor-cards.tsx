import { Languages, MapPin, Stethoscope } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Doctor } from "@/lib/types";

/**
 * Suggested doctors as cards. The options arrive as data in the `message` event, in the same
 * order the assistant numbers them, so "Book" sends "Book number N" for exactly that doctor.
 */
export function DoctorCards({
  doctors,
  enabled,
  onBook,
}: {
  doctors: Doctor[];
  enabled: boolean;
  onBook: (number: number) => void;
}) {
  return (
    <ul aria-label="Suggested doctors" className="mt-2 grid gap-2 sm:grid-cols-2">
      {doctors.map((doctor, index) => (
        <li key={doctor.id} className="bg-card flex flex-col rounded-xl border p-3 shadow-xs">
          <div className="flex items-start gap-3">
            <span
              aria-hidden
              className="bg-accent text-primary flex size-9 shrink-0 items-center justify-center rounded-lg text-sm font-semibold"
            >
              {index + 1}
            </span>
            <div className="min-w-0">
              <p className="font-medium">{doctor.name}</p>
              <ul className="text-muted-foreground mt-1 space-y-0.5 text-xs">
                <li className="flex items-center gap-1.5">
                  <Stethoscope className="size-3.5 shrink-0" aria-hidden />
                  {doctor.specialty}
                </li>
                <li className="flex items-center gap-1.5">
                  <MapPin className="size-3.5 shrink-0" aria-hidden />
                  {doctor.city}
                </li>
                <li className="flex items-center gap-1.5">
                  <Languages className="size-3.5 shrink-0" aria-hidden />
                  {doctor.languages.join(", ")}
                </li>
              </ul>
            </div>
          </div>
          <Button
            variant="outline"
            size="lg"
            className="mt-3 h-9 w-full"
            disabled={!enabled}
            onClick={() => onBook(index + 1)}
            aria-label={`Book ${doctor.name}`}
          >
            Book
          </Button>
        </li>
      ))}
    </ul>
  );
}
