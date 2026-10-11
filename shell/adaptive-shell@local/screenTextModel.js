// Pure OCR geometry and selection helpers, shared by GJS and the verifier.
/* exported parseTsv, mapWords, hitWord, passage, lineWords, selectionText */

function parseTsv(tsv, monitor = 0) {
    const words = [];
    for (const row of tsv.split(/\r?\n/)) {
        const cells = row.split('\t');
        if (cells.length < 12 || cells[0] !== '5')
            continue;
        const values = cells.slice(1, 11).map(Number);
        const [page, block, paragraph, line, word, x, y, width, height, confidence] = values;
        const text = cells.slice(11).join('\t').trim();
        if (!text || values.some(v => !Number.isFinite(v)) || confidence < 0 ||
            x < 0 || y < 0 || width <= 0 || height <= 0)
            continue;
        words.push({ text, x, y, width, height, page, block, paragraph, line, word,
            blockId: `${monitor}:${page}:${block}`, lineId: `${monitor}:${page}:${block}:${paragraph}:${line}` });
    }
    return words.sort((a, b) => a.page - b.page || a.block - b.block ||
        a.paragraph - b.paragraph || a.line - b.line || a.word - b.word);
}

function mapWords(words, imageWidth, imageHeight, rect) {
    if (imageWidth <= 0 || imageHeight <= 0)
        return [];
    return words.filter(w => w.x + w.width <= imageWidth && w.y + w.height <= imageHeight)
        .map(w => ({ ...w, x: rect.x + w.x * rect.width / imageWidth,
            y: rect.y + w.y * rect.height / imageHeight,
            width: w.width * rect.width / imageWidth, height: w.height * rect.height / imageHeight }));
}

function hitWord(words, x, y) {
    return words.findIndex(w => x >= w.x && x <= w.x + w.width && y >= w.y && y <= w.y + w.height);
}

function passage(words, anchor, end) {
    if (!words[anchor] || !words[end] || words[anchor].blockId !== words[end].blockId)
        return [];
    const start = Math.min(anchor, end), stop = Math.max(anchor, end);
    return words.map((_, i) => i).filter(i => i >= start && i <= stop && words[i].blockId === words[anchor].blockId);
}

function lineWords(words, index) {
    return words[index] ? words.map((_, i) => i).filter(i => words[i].lineId === words[index].lineId) : [];
}

function selectionText(words, indices) {
    let text = '', previous = null;
    for (const i of [...new Set(indices)].sort((a, b) => a - b)) {
        const word = words[i];
        if (!word)
            continue;
        if (previous)
            text += previous.blockId !== word.blockId ? '\n\n' : previous.lineId !== word.lineId ? '\n' : ' ';
        text += word.text;
        previous = word;
    }
    return text;
}
