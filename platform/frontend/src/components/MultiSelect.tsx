import { ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuLabel, DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

/** A compact multi-select: a button showing the choice, a menu of checkable options. */
export function MultiSelect({ label, options, value, onChange, emptyText = "Any" }: {
  label: string; options: string[]; value: string[]; onChange: (value: string[]) => void; emptyText?: string;
}) {
  const summary = value.length === 0 ? emptyText : value.length <= 2 ? value.join(", ") : `${value.length} selected`;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" className="h-9 w-full justify-between font-normal" aria-label={label}>
          <span className="truncate">{summary}</span>
          <ChevronDown className="opacity-50" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-56">
        <DropdownMenuLabel>{label}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {options.map((option) => (
          <DropdownMenuCheckboxItem
            key={option}
            checked={value.includes(option)}
            onSelect={(event) => event.preventDefault()}
            onCheckedChange={(checked) =>
              onChange(checked ? options.filter((o) => o === option || value.includes(o)) : value.filter((o) => o !== option))}
          >
            {option}
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
