import type { DisplayMessage } from "./ChatPage";
import { AbstainedNotice } from "./AbstainedNotice";
import { AnswerText } from "./AnswerText";
import { CitationList } from "./CitationList";
import { Disclaimer } from "./Disclaimer";

export function MessageBubble({ message }: { message: DisplayMessage }) {
  if (message.role === "system") {
    return (
      <div className="mx-auto max-w-md rounded bg-slate-100 px-3 py-2 text-center text-xs text-slate-500">
        {message.content}
      </div>
    );
  }

  if (message.role === "user") {
    return (
      <div className="ml-auto max-w-lg rounded-lg bg-slate-900 px-4 py-2 text-sm text-white">
        {message.content}
      </div>
    );
  }

  return (
    <div className="mr-auto max-w-2xl rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-800">
      {message.abstained ? (
        <AbstainedNotice>{message.content}</AbstainedNotice>
      ) : (
        <AnswerText text={message.content} />
      )}
      {message.citations && message.citations.length > 0 && (
        <CitationList citations={message.citations} />
      )}
      {message.disclaimer && <Disclaimer disclaimer={message.disclaimer} />}
    </div>
  );
}
