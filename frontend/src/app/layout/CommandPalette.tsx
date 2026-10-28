import * as Dialog from "@radix-ui/react-dialog";
import { Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { cn } from "@/lib/utils";
import { useActivities, useSystems } from "../hooks/data";
import { NAV } from "../permissions";
import { useSession } from "../session";

interface Entry {
  id: string;
  label: string;
  group: string;
  to: string;
}

/** Ctrl K: jump to a page, a system or a record, or start common work. */
export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[65] bg-navy/60" />
        <Dialog.Content
          className="fixed left-1/2 top-[12vh] z-[66] w-[min(36rem,calc(100vw-2rem))] -translate-x-1/2 overflow-hidden rounded-lg bg-background shadow-pop"
          aria-describedby={undefined}
        >
          <Dialog.Title className="sr-only">Command palette</Dialog.Title>
          <PaletteBody onDone={() => onOpenChange(false)} />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function PaletteBody({ onDone }: { onDone: () => void }) {
  const { me, can } = useSession();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const listRef = useRef<HTMLUListElement>(null);
  const systems = useSystems();
  const activities = useActivities();

  const entries = useMemo<Entry[]>(() => {
    const out: Entry[] = NAV.filter((n) => n.roles.includes(me.role) && (!n.host || me.is_host)).map((n) => ({
      id: `nav:${n.to}`,
      label: n.label,
      group: "Pages",
      to: n.to,
    }));
    if (can("write")) {
      out.unshift(
        { id: "act:system", label: "Add a system", group: "Actions", to: "/app/systems/new" },
        { id: "act:request", label: "Log an access request", group: "Actions", to: "/app/requests?new=1" },
      );
    }
    for (const s of systems.data ?? [])
      out.push({ id: `sys:${s.id}`, label: s.name, group: "Systems", to: `/app/systems/${s.id}` });
    for (const a of activities.data ?? [])
      out.push({ id: `rec:${a.id}`, label: a.name, group: "Records", to: `/app/records/${a.id}` });
    return out;
  }, [me.role, me.is_host, can, systems.data, activities.data]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (q ? entries.filter((e) => e.label.toLowerCase().includes(q)) : entries).slice(0, 30);
  }, [entries, query]);

  useEffect(() => {
    listRef.current?.children[active]?.scrollIntoView?.({ block: "nearest" });
  }, [active]);

  const go = (entry: Entry | undefined) => {
    if (!entry) return;
    onDone();
    navigate(entry.to);
  };

  return (
    <>
      <div className="flex items-center gap-2 border-b border-border px-4">
        <Search aria-hidden="true" className="size-4 text-muted-foreground" />
        <input
          role="combobox"
          aria-expanded="true"
          aria-controls="palette-list"
          aria-activedescendant={shown[active] ? `palette-${shown[active].id}` : undefined}
          aria-label="Search pages, systems and records"
          placeholder="Search pages, systems and records"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActive(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((a) => Math.min(a + 1, shown.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((a) => Math.max(a - 1, 0));
            } else if (e.key === "Enter") {
              e.preventDefault();
              go(shown[active]);
            }
          }}
          className="h-12 flex-1 bg-transparent text-base outline-none placeholder:text-muted-foreground"
        />
      </div>
      <ul id="palette-list" role="listbox" ref={listRef} className="max-h-80 overflow-y-auto p-2">
        {shown.length === 0 && <li className="px-3 py-6 text-center text-sm text-muted-foreground">Nothing found.</li>}
        {shown.map((e, i) => (
          // The input handles the keyboard (arrows and Enter); a click is the pointer shortcut for the same action.
          // eslint-disable-next-line jsx-a11y/click-events-have-key-events
          <li
            key={e.id}
            id={`palette-${e.id}`}
            role="option"
            aria-selected={i === active}
            onMouseMove={() => setActive(i)}
            onClick={() => go(e)}
            className={cn(
              "flex cursor-pointer items-center justify-between rounded-md px-3 py-2 text-sm",
              i === active && "bg-primary/10",
            )}
          >
            <span>{e.label}</span>
            <span className="text-xs text-muted-foreground">{e.group}</span>
          </li>
        ))}
      </ul>
    </>
  );
}
