import type { ReactNode } from 'react';

type RagLayoutProps = {
  sidebar: ReactNode;
  main: ReactNode;
};

export default function RagLayout({ sidebar, main }: RagLayoutProps) {
  return (
    <div className="rag-layout">
      <aside className="rag-sidebar">{sidebar}</aside>
      <main className="rag-main">{main}</main>
    </div>
  );
}
