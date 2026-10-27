import ReactMarkdown from "react-markdown";

/** Renders project Markdown. Raw HTML in the source is not rendered (react-markdown escapes it). */
export default function MarkdownView({ text }: { text: string }) {
  return (
    <div className="prose-doc">
      <ReactMarkdown
        components={{
          // Wide code blocks and tables scroll, so they must be reachable from the keyboard.
          // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
          pre: ({ children }) => <pre tabIndex={0}>{children}</pre>,
          // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
          table: ({ children }) => <table tabIndex={0}>{children}</table>,
          a: ({ href, children }) => {
            const external = typeof href === "string" && /^https?:/.test(href);
            return (
              <a href={href} {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}>
                {children}
              </a>
            );
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
