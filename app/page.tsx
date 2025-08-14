import React from "react";

function Section({
  id,
  title,
  subtitle,
  children,
}: { id: string; title: string; subtitle?: string; children: React.ReactNode }) {
  const apiHref = `/api/${id.replace("-", "")}`;

  return (
    <section id={id} className="mx-auto max-w-7xl px-4 py-6 md:py-8">
      <div className="mb-4 flex items-end justify-between">
        <div>
          <h2 className="text-xl font-semibold text-white md:text-2xl">{title}</h2>
          {subtitle && <p className="mt-1 text-sm text-neutral-400">{subtitle}</p>}
        </div>
        <a
          href={apiHref}
          className="text-xs text-neutral-400 hover:text-neutral-200"
        >
          API
        </a>
      </div>
      {children}
    </section>
  );
}
