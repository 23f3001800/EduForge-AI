import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge class names, letting a caller override a component default.
 *
 * `twMerge` is what makes `<Button className="bg-danger">` actually win over
 * the variant background instead of both landing in the class list and letting
 * source order decide.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
