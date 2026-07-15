import SwiftUI

/// Lightweight block-level Markdown renderer for coach replies and the plan.
///
/// `AttributedString(markdown:)` only handles inline styling, so this splits
/// the text into blocks (headings, bullet/numbered list items, paragraphs)
/// and renders each block with inline Markdown parsing applied.
struct MarkdownText: View {
    let markdown: String

    private var blocks: [MarkdownBlock] {
        MarkdownBlock.parse(markdown)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(blocks) { block in
                blockView(block)
            }
        }
    }

    @ViewBuilder
    private func blockView(_ block: MarkdownBlock) -> some View {
        switch block.kind {
        case .heading(let level):
            Text(inline(block.text))
                .font(level <= 1 ? .title3.bold() : level == 2 ? .headline : .subheadline.bold())
                .padding(.top, 4)
        case .bullet(let indent):
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("•")
                    .font(.body)
                    .foregroundStyle(.secondary)
                Text(inline(block.text))
                    .font(.body)
            }
            .padding(.leading, CGFloat(indent) * 16)
        case .numbered(let number):
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("\(number).")
                    .font(.body.monospacedDigit())
                    .foregroundStyle(.secondary)
                Text(inline(block.text))
                    .font(.body)
            }
        case .paragraph:
            Text(inline(block.text))
                .font(.body)
        }
    }

    /// Inline bold/italic/code/link parsing via Foundation's Markdown support;
    /// falls back to the raw text if parsing fails.
    private func inline(_ text: String) -> AttributedString {
        (try? AttributedString(
            markdown: text,
            options: AttributedString.MarkdownParsingOptions(
                interpretedSyntax: .inlineOnlyPreservingWhitespace)))
            ?? AttributedString(text)
    }
}

struct MarkdownBlock: Identifiable {
    enum Kind {
        case heading(level: Int)
        case bullet(indent: Int)
        case numbered(number: Int)
        case paragraph
    }

    let id: Int
    let kind: Kind
    let text: String

    /// Splits raw Markdown into simple blocks. Consecutive plain lines are
    /// merged into one paragraph; blank lines separate paragraphs.
    static func parse(_ markdown: String) -> [MarkdownBlock] {
        var blocks: [MarkdownBlock] = []
        var paragraph: [String] = []
        var nextID = 0

        func flushParagraph() {
            guard !paragraph.isEmpty else { return }
            let text = paragraph.joined(separator: " ")
            blocks.append(MarkdownBlock(id: nextID, kind: .paragraph, text: text))
            nextID += 1
            paragraph = []
        }

        for rawLine in markdown.components(separatedBy: .newlines) {
            let line = rawLine.trimmingCharacters(in: .whitespaces)
            if line.isEmpty {
                flushParagraph()
                continue
            }

            // Headings: "#", "##", "###"…
            if line.hasPrefix("#") {
                flushParagraph()
                let level = line.prefix(while: { $0 == "#" }).count
                let text = line.drop(while: { $0 == "#" }).trimmingCharacters(in: .whitespaces)
                blocks.append(MarkdownBlock(id: nextID, kind: .heading(level: level), text: text))
                nextID += 1
                continue
            }

            // Bulleted list items: "-", "*", "+" (with indentation for nesting).
            if line.hasPrefix("- ") || line.hasPrefix("* ") || line.hasPrefix("+ ") {
                flushParagraph()
                let leadingSpaces = rawLine.prefix(while: { $0 == " " }).count
                let text = String(line.dropFirst(2)).trimmingCharacters(in: .whitespaces)
                blocks.append(MarkdownBlock(
                    id: nextID,
                    kind: .bullet(indent: min(leadingSpaces / 2, 3)),
                    text: text))
                nextID += 1
                continue
            }

            // Numbered list items: "1. ", "12. "…
            if let dotIndex = line.firstIndex(of: "."),
               let number = Int(line[line.startIndex ..< dotIndex]),
               line.index(after: dotIndex) < line.endIndex,
               line[line.index(after: dotIndex)] == " " {
                flushParagraph()
                let text = String(line[line.index(dotIndex, offsetBy: 2)...])
                    .trimmingCharacters(in: .whitespaces)
                blocks.append(MarkdownBlock(id: nextID, kind: .numbered(number: number), text: text))
                nextID += 1
                continue
            }

            paragraph.append(line)
        }
        flushParagraph()
        return blocks
    }
}
