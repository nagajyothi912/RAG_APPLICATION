import type { ReactNode } from 'react';

type RagLayoutProps = {
  sidebar: ReactNode;
  main: ReactNode;
  /** The chatbot: a narrower library column and a full-width chat. */
  wide?: boolean;
};

export default function RagLayout({ sidebar, main, wide = false }: RagLayoutProps) {
  return (
    <div className={`rag-layout ${wide ? 'rag-layout--wide' : ''}`}>
      <aside className="rag-sidebar">{sidebar}</aside>
      <main className="rag-main">{main}</main>
    </div>
  );
}
