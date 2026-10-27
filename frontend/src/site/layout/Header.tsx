import * as NavigationMenu from "@radix-ui/react-navigation-menu";
import { ChevronDown, Menu } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, NavLink } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { Logo } from "../art/Logo";
import { navGroups } from "../content/site";

const utility = [
  { label: "Contact", to: "/contact" },
  { label: "Documentation", to: "/resources#documentation" },
  { label: "Status", to: "/status" },
];

function useScrolled(threshold = 24): boolean {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > threshold);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [threshold]);
  return scrolled;
}

function MobileMenu() {
  const [open, setOpen] = useState(false);
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open menu">
          <Menu aria-hidden="true" className="size-6" />
        </Button>
      </SheetTrigger>
      <SheetContent>
        <SheetTitle className="mb-1 text-lg font-semibold text-navy">Menu</SheetTitle>
        <SheetDescription className="sr-only">Site navigation</SheetDescription>
        <nav aria-label="Mobile" className="mt-4 space-y-6">
          {navGroups.map((group) => (
            <div key={group.label}>
              <SheetClose asChild>
                <Link to={group.to} className="text-base font-semibold text-navy">
                  {group.label}
                </Link>
              </SheetClose>
              <ul className="mt-2 space-y-1 border-l border-border pl-4">
                {group.links.map((l) => (
                  <li key={l.to}>
                    <SheetClose asChild>
                      <Link to={l.to} className="block py-1.5 text-sm text-muted-foreground hover:text-primary">
                        {l.label}
                      </Link>
                    </SheetClose>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        <div className="mt-8 flex flex-col gap-3">
          <SheetClose asChild>
            <Button asChild variant="secondary">
              <Link to="/login">Sign in</Link>
            </Button>
          </SheetClose>
          <SheetClose asChild>
            <Button asChild>
              <Link to="/login">Open console</Link>
            </Button>
          </SheetClose>
        </div>
      </SheetContent>
    </Sheet>
  );
}

export function Header() {
  const scrolled = useScrolled();
  return (
    <header className={cn("sticky top-0 z-40 bg-background transition-shadow", scrolled && "shadow-header")}>
      <div
        className={cn("hidden bg-navy text-white transition-all md:block", scrolled ? "h-0 overflow-hidden" : "h-9")}
      >
        <div className="container flex h-9 items-center justify-between text-xs">
          <span className="text-white/80">Demonstration environment with sample data</span>
          <nav aria-label="Utility" className="flex gap-5">
            {utility.map((u) => (
              <Link key={u.label} to={u.to} className="text-white/90 hover:text-white hover:underline">
                {u.label}
              </Link>
            ))}
          </nav>
        </div>
      </div>
      <div className="container flex items-center justify-between gap-4" style={{ height: scrolled ? 60 : 76 }}>
        <Link to="/" aria-label="ProcessLedger home" className="shrink-0">
          <Logo />
        </Link>
        <NavigationMenu.Root className="relative hidden lg:block" aria-label="Main">
          <NavigationMenu.List className="flex items-center gap-1">
            {navGroups.map((group) => (
              <NavigationMenu.Item key={group.label} className="relative">
                <NavigationMenu.Trigger className="group inline-flex h-10 items-center gap-1 rounded-md px-3 text-sm font-semibold text-navy hover:bg-muted data-[state=open]:bg-muted">
                  {group.label}
                  <ChevronDown
                    aria-hidden="true"
                    className="size-4 transition-transform group-data-[state=open]:rotate-180"
                  />
                </NavigationMenu.Trigger>
                <NavigationMenu.Content className="absolute left-0 top-full z-50 pt-2">
                  <div className="grid w-[560px] grid-cols-[200px_1fr] gap-6 rounded-lg border border-border bg-background p-5 shadow-pop">
                    <div>
                      <NavigationMenu.Link asChild>
                        <Link to={group.to} className="text-base font-semibold text-navy hover:text-primary">
                          {group.label}
                        </Link>
                      </NavigationMenu.Link>
                      <p className="mt-2 text-sm text-muted-foreground">{group.intro}</p>
                    </div>
                    <ul className="grid gap-1">
                      {group.links.map((l) => (
                        <li key={l.to}>
                          <NavigationMenu.Link asChild>
                            <Link to={l.to} className="block rounded-md p-2.5 hover:bg-muted">
                              <span className="block text-sm font-semibold text-navy">{l.label}</span>
                              {l.description && (
                                <span className="block text-xs text-muted-foreground">{l.description}</span>
                              )}
                            </Link>
                          </NavigationMenu.Link>
                        </li>
                      ))}
                    </ul>
                  </div>
                </NavigationMenu.Content>
              </NavigationMenu.Item>
            ))}
          </NavigationMenu.List>
        </NavigationMenu.Root>
        <div className="flex items-center gap-2">
          <NavLink to="/login" className="hidden px-3 text-sm font-semibold text-navy hover:text-primary sm:inline">
            Sign in
          </NavLink>
          <Button asChild className="hidden sm:inline-flex">
            <Link to="/login">Open console</Link>
          </Button>
          <MobileMenu />
        </div>
      </div>
    </header>
  );
}
