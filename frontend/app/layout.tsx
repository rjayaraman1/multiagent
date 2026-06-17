import './globals.css';

export const metadata = {
  title: 'Multi-Agent-VedicAstro-RAG-Pipeline',
  description: 'Final RAG agent — LangGraph + LangChain + Next.js + FastAPI',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
