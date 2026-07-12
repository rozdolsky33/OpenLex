import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { AnswerText } from "./AnswerText";

describe("AnswerText", () => {
  it("renders **bold** markdown as actual bold text, not literal asterisks", () => {
    render(<AnswerText text="For **Non-Payment of Rent:** the landlord must serve notice." />);
    const bold = screen.getByText("Non-Payment of Rent:");
    expect(bold.tagName).toBe("STRONG");
    expect(screen.queryByText(/\*\*/)).not.toBeInTheDocument();
  });

  it("renders plain text with no markdown unchanged", () => {
    render(<AnswerText text="A tenant shall include an occupant of one or more rooms." />);
    expect(
      screen.getByText("A tenant shall include an occupant of one or more rooms."),
    ).toBeInTheDocument();
  });

  it("splits double-newline-separated text into separate paragraphs", () => {
    const { container } = render(<AnswerText text={"First paragraph.\n\nSecond paragraph."} />);
    const paragraphs = container.querySelectorAll("p");
    expect(paragraphs).toHaveLength(2);
    expect(paragraphs[0]).toHaveTextContent("First paragraph.");
    expect(paragraphs[1]).toHaveTextContent("Second paragraph.");
  });
});
