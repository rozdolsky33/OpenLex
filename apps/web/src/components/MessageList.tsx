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
    <div className="flex flex-1 flex-col gap-3 overflow-y-auto px-4 py-4">
      {messages.length === 0 && !pending && (
        <p className="mx-auto mt-8 text-sm text-slate-400">
          Ask a question about NY landlord-tenant law to get started.
        </p>
      )}
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}
      {pending && <LoadingIndicator />}
      <div ref={bottomRef} />
    </div>
  );
}
