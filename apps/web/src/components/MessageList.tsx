import { useEffect, useRef } from "react";
import type { DisplayMessage } from "./ChatPage";
import { LoadingIndicator } from "./LoadingIndicator";
import { MessageBubble } from "./MessageBubble";

export function MessageList({
  messages,
  pending,
}: {
  messages: DisplayMessage[];
  pending: boolean;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, pending]);

  return (
    <div className="flex flex-1 flex-col overflow-y-auto px-4 py-6">
      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-3">
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}
        {pending && <LoadingIndicator />}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
