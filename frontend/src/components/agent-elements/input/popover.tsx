import * as React from "react";

import type { ReactNode } from "react";
import { Popover as BasePopover } from "@base-ui/react/popover";
import { cn } from "../utils/cn";

export type PopoverSide = "top" | "bottom" | "left" | "right";
export type PopoverAlign = "start" | "center" | "end";

export type PopoverProps = {
  trigger: ReactNode;
  children: ReactNode;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  side?: PopoverSide;
  align?: PopoverAlign;
  sideOffset?: number;
  className?: string;
};

export function Popover({
  trigger,
  children,
  open,
  defaultOpen,
  onOpenChange,
  side = "top",
  align = "start",
  sideOffset = 6,
  className,
}: PopoverProps) {
  const anchorRef = React.useRef<HTMLSpanElement>(null);
  return (
    <BasePopover.Root
      open={open}
      defaultOpen={defaultOpen}
      onOpenChange={onOpenChange ? (next) => onOpenChange(next) : undefined}
    >
      <span ref={anchorRef} className="inline-flex min-w-0">
        <BasePopover.Trigger render={trigger as React.ReactElement} />
      </span>
      <BasePopover.Portal container={anchorRef.current?.closest<HTMLElement>(".library-composer") ?? undefined}>
        <BasePopover.Positioner side={side} align={align} sideOffset={sideOffset}>
          <BasePopover.Popup
            aria-label="Choose a model"
            className={cn(
              "an-model-popup min-w-[240px] max-w-[min(360px,calc(100vw-32px))] max-h-[320px] overflow-y-auto rounded-[10px] border border-an-border-color bg-an-background p-1 shadow-lg outline-none",
              "text-an-foreground",
              className,
            )}
          >
            {children}
          </BasePopover.Popup>
        </BasePopover.Positioner>
      </BasePopover.Portal>
    </BasePopover.Root>
  );
}
