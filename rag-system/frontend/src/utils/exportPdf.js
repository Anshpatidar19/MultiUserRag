import jsPDF from "jspdf";

/**
 * Renders a conversation transcript to a simple text-based PDF (not a
 * screenshot render) so it stays small and the text is selectable/
 * searchable in the exported file.
 */
export function exportConversationToPdf(sessionTitle, messages) {
  const doc = new jsPDF({ unit: "pt", format: "a4" });
  const marginX = 48;
  let y = 56;
  const pageHeight = doc.internal.pageSize.getHeight();
  const maxWidth = doc.internal.pageSize.getWidth() - marginX * 2;

  doc.setFontSize(16);
  doc.setFont(undefined, "bold");
  doc.text(sessionTitle || "Conversation", marginX, y);
  y += 28;

  doc.setFontSize(10);
  doc.setTextColor(120);
  doc.text(new Date().toLocaleString(), marginX, y);
  y += 24;
  doc.setTextColor(20);

  messages.forEach((m) => {
    const speaker = m.role === "user" ? "You" : "Assistant";
    doc.setFont(undefined, "bold");
    doc.setFontSize(11);
    if (y > pageHeight - 60) {
      doc.addPage();
      y = 56;
    }
    doc.text(speaker, marginX, y);
    y += 16;

    doc.setFont(undefined, "normal");
    doc.setFontSize(11);
    const lines = doc.splitTextToSize(m.content || "", maxWidth);
    lines.forEach((line) => {
      if (y > pageHeight - 60) {
        doc.addPage();
        y = 56;
      }
      doc.text(line, marginX, y);
      y += 15;
    });

    if (m.citations?.length) {
      doc.setFontSize(9);
      doc.setTextColor(130);
      m.citations.forEach((c) => {
        if (y > pageHeight - 60) {
          doc.addPage();
          y = 56;
        }
        doc.text(`Source: ${c.source_name} (relevance ${c.relevance_score})`, marginX, y);
        y += 12;
      });
      doc.setTextColor(20);
    }

    y += 14;
  });

  doc.save(`${(sessionTitle || "conversation").replace(/\s+/g, "_")}.pdf`);
}
