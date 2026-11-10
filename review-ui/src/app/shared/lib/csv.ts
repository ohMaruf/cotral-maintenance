/**
 * Minimal RFC 4180 parser: comma separated, fields may be quoted with `""` as the
 * escaped quote, and quoted fields may contain commas and line breaks. Handles
 * `\n`, `\r\n` and a leading BOM. Blank lines are skipped.
 */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = '';
  let quoted = false;
  let started = false; // anything seen on this row (distinguishes a blank line)

  const endField = () => {
    row.push(field);
    field = '';
  };
  const endRow = () => {
    if (started || row.length > 0) {
      endField();
      rows.push(row);
    }
    row = [];
    started = false;
  };

  const src = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
  for (let i = 0; i < src.length; i++) {
    const ch = src[i];
    if (quoted) {
      if (ch === '"') {
        if (src[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          quoted = false;
        }
      } else {
        field += ch;
      }
      continue;
    }
    if (ch === '"' && field === '') {
      quoted = true;
      started = true;
    } else if (ch === ',') {
      started = true;
      endField();
    } else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && src[i + 1] === '\n') i++;
      endRow();
    } else {
      started = true;
      field += ch;
    }
  }
  endRow();
  return rows;
}

/** Rows as objects keyed by the header row; short rows get empty strings. */
export function parseCsvRecords(text: string): Record<string, string>[] {
  const [header, ...body] = parseCsv(text);
  if (!header) return [];
  const names = header.map((h) => h.trim());
  return body.map((cells) => {
    const record: Record<string, string> = {};
    names.forEach((name, i) => (record[name] = cells[i] ?? ''));
    return record;
  });
}

/** Serialises one field the way the old shape-check page did. */
export function csvField(value: string): string {
  return /[",\n\r]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value;
}
