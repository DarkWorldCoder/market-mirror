import * as React from "react";
import { IconArrowUp, IconPlayerStopFilled } from "@tabler/icons-react";
import { cn } from "../utils/cn";

export type SendButtonProps = {
  state: "idle" | "typing" | "streaming";
};

export function SendButton({ state }: SendButtonProps) {
  const isStreaming = state === "streaming";
  const isTyping = state === "typing";

  if (isStreaming) {
    return (
      <div className="size-9 rounded-full bg-foreground flex items-center justify-center cursor-pointer">
        <IconPlayerStopFilled className="size-4.5 text-background" />
      </div>
    );
  }

  return (
    <div
      className={cn(
        "size-9 rounded-full flex items-center justify-center",
        isTyping
          ? "bg-an-send-button-bg cursor-pointer"
          : "bg-muted cursor-default",
      )}
    >
      <IconArrowUp
        className={cn(
          "size-4.5",
          isTyping
            ? "text-an-send-button-color"
            : "text-neutral-400 dark:text-neutral-600",
        )}
      />
    </div>
  );
}
