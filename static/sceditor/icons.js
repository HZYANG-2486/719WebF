/* SCEditor Simple SVG Icons */
(function() {
    "use strict";

    var iconPaths = {
        bold: '<svg viewBox="0 0 16 16"><path d="M4 3h4a2.5 2.5 0 0 1 0 5H4zM4 8h5a2.5 2.5 0 0 1 0 5H4z"/></svg>',
        italic: '<svg viewBox="0 0 16 16"><line x1="6" y1="3" x2="12" y2="3" stroke="#333" stroke-width="1.5"/><line x1="4" y1="13" x2="10" y2="13" stroke="#333" stroke-width="1.5"/><line x1="10" y1="3" x2="6" y2="13" stroke="#333" stroke-width="1.5"/></svg>',
        underline: '<svg viewBox="0 0 16 16"><path d="M4 3v6a4 4 0 0 0 8 0V3" stroke="#333" stroke-width="1.5" fill="none"/><line x1="3" y1="13" x2="13" y2="13" stroke="#333" stroke-width="1.5"/></svg>',
        strike: '<svg viewBox="0 0 16 16"><line x1="3" y1="8" x2="13" y2="8" stroke="#333" stroke-width="1.5"/><line x1="5" y1="4" x2="11" y2="4" stroke="#333" stroke-width="1.2"/><line x1="5" y1="12" x2="11" y2="12" stroke="#333" stroke-width="1.2"/><line x1="7" y1="4" x2="5" y2="12" stroke="#333" stroke-width="1.2"/><line x1="9" y1="4" x2="11" y2="12" stroke="#333" stroke-width="1.2"/></svg>',
        color: '<svg viewBox="0 0 16 16"><rect x="2" y="2" width="12" height="12" rx="1" fill="none" stroke="#333" stroke-width="1.2"/><rect x="4" y="4" width="3" height="3" fill="#e74c3c"/><rect x="9" y="4" width="3" height="3" fill="#3498db"/><rect x="4" y="9" width="3" height="3" fill="#f1c40f"/><rect x="9" y="9" width="3" height="3" fill="#2ecc71"/></svg>',
        size: '<svg viewBox="0 0 16 16"><text x="8" y="13" font-size="12" font-weight="bold" text-anchor="middle" fill="#333" font-family="Arial">A</text></svg>',
        font: '<svg viewBox="0 0 16 16"><text x="8" y="12" font-size="11" font-weight="bold" text-anchor="middle" fill="#333" font-family="Arial">F</text></svg>',
        link: '<svg viewBox="0 0 16 16"><path d="M6 8a3 3 0 0 0 4.24 0l2.83-2.83a3 3 0 0 0-4.24-4.24L7.05 2.34" stroke="#333" stroke-width="1.2" fill="none"/><path d="M10 8a3 3 0 0 0-4.24 0L2.93 10.83a3 3 0 0 0 4.24 4.24l1.78-.92" stroke="#333" stroke-width="1.2" fill="none"/></svg>',
        unlink: '<svg viewBox="0 0 16 16"><path d="M6 8a3 3 0 0 0 4.24 0l2.83-2.83a3 3 0 0 0-4.24-4.24L7.05 2.34" stroke="#333" stroke-width="1.2" fill="none"/><path d="M10 8a3 3 0 0 0-4.24 0L2.93 10.83a3 3 0 0 0 4.24 4.24l1.78-.92" stroke="#333" stroke-width="1.2" fill="none"/><line x1="3" y1="3" x2="13" y2="13" stroke="#333" stroke-width="1.5"/></svg>',
        image: '<svg viewBox="0 0 16 16"><rect x="2" y="3" width="12" height="10" rx="1" fill="none" stroke="#333" stroke-width="1.2"/><circle cx="6" cy="6" r="1.5" fill="#333"/><polyline points="3,12 6,8 9,11 11,9 13,12" stroke="#333" stroke-width="1.2" fill="none"/></svg>',
        code: '<svg viewBox="0 0 16 16"><polyline points="6,4 2,8 6,12" stroke="#333" stroke-width="1.5" fill="none" stroke-linecap="round"/><polyline points="10,4 14,8 10,12" stroke="#333" stroke-width="1.5" fill="none" stroke-linecap="round"/><line x1="9" y1="3" x2="7" y2="13" stroke="#333" stroke-width="1.5" stroke-linecap="round"/></svg>',
        source: '<svg viewBox="0 0 16 16"><rect x="2" y="3" width="12" height="10" rx="1" fill="none" stroke="#333" stroke-width="1.2"/><text x="8" y="11" font-size="7" font-weight="bold" text-anchor="middle" fill="#333" font-family="monospace">HTML</text></svg>',
        quote: '<svg viewBox="0 0 16 16"><path d="M5 4h3v3H5a2 2 0 0 0 0 4" stroke="#333" stroke-width="1.2" fill="none"/><path d="M11 4h3v3h-3a2 2 0 0 0 0 4" stroke="#333" stroke-width="1.2" fill="none"/></svg>',
        center: '<svg viewBox="0 0 16 16"><line x1="2" y1="4" x2="14" y2="4" stroke="#333" stroke-width="1.5"/><line x1="4" y1="8" x2="12" y2="8" stroke="#333" stroke-width="1.5"/><line x1="3" y1="12" x2="13" y2="12" stroke="#333" stroke-width="1.5"/></svg>',
        left: '<svg viewBox="0 0 16 16"><line x1="2" y1="4" x2="14" y2="4" stroke="#333" stroke-width="1.5"/><line x1="2" y1="8" x2="10" y2="8" stroke="#333" stroke-width="1.5"/><line x1="2" y1="12" x2="12" y2="12" stroke="#333" stroke-width="1.5"/></svg>',
        right: '<svg viewBox="0 0 16 16"><line x1="2" y1="4" x2="14" y2="4" stroke="#333" stroke-width="1.5"/><line x1="6" y1="8" x2="14" y2="8" stroke="#333" stroke-width="1.5"/><line x1="4" y1="12" x2="14" y2="12" stroke="#333" stroke-width="1.5"/></svg>',
        justify: '<svg viewBox="0 0 16 16"><line x1="2" y1="4" x2="14" y2="4" stroke="#333" stroke-width="1.5"/><line x1="2" y1="8" x2="14" y2="8" stroke="#333" stroke-width="1.5"/><line x1="2" y1="12" x2="14" y2="12" stroke="#333" stroke-width="1.5"/></svg>',
        bulletlist: '<svg viewBox="0 0 16 16"><circle cx="3" cy="5" r="1" fill="#333"/><circle cx="3" cy="11" r="1" fill="#333"/><line x1="6" y1="5" x2="14" y2="5" stroke="#333" stroke-width="1.2"/><line x1="6" y1="11" x2="14" y2="11" stroke="#333" stroke-width="1.2"/><line x1="5" y1="8" x2="14" y2="8" stroke="#333" stroke-width="1.2"/><line x1="5" y1="14" x2="14" y2="14" stroke="#333" stroke-width="1.2"/></svg>',
        orderedlist: '<svg viewBox="0 0 16 16"><text x="1" y="7" font-size="5" font-weight="bold" fill="#333">1.</text><text x="1" y="13" font-size="5" font-weight="bold" fill="#333">2.</text><line x1="7" y1="5" x2="14" y2="5" stroke="#333" stroke-width="1.2"/><line x1="7" y1="11" x2="14" y2="11" stroke="#333" stroke-width="1.2"/></svg>',
        table: '<svg viewBox="0 0 16 16"><rect x="2" y="3" width="12" height="10" fill="none" stroke="#333" stroke-width="1.2"/><line x1="2" y1="7" x2="14" y2="7" stroke="#333" stroke-width="1"/><line x1="2" y1="11" x2="14" y2="11" stroke="#333" stroke-width="1"/><line x1="6" y1="3" x2="6" y2="13" stroke="#333" stroke-width="1"/><line x1="10" y1="3" x2="10" y2="13" stroke="#333" stroke-width="1"/></svg>',
        horizontalrule: '<svg viewBox="0 0 16 16"><line x1="2" y1="8" x2="14" y2="8" stroke="#333" stroke-width="2"/></svg>',
        superscript: '<svg viewBox="0 0 16 16"><text x="3" y="12" font-size="8" font-weight="bold" fill="#333">X</text><text x="9" y="5" font-size="6" font-weight="bold" fill="#333">2</text></svg>',
        subscript: '<svg viewBox="0 0 16 16"><text x="3" y="10" font-size="8" font-weight="bold" fill="#333">X</text><text x="9" y="14" font-size="6" font-weight="bold" fill="#333">2</text></svg>',
        cut: '<svg viewBox="0 0 16 16"><circle cx="5" cy="8" r="3" fill="none" stroke="#333" stroke-width="1.2"/><circle cx="11" cy="8" r="3" fill="none" stroke="#333" stroke-width="1.2"/><line x1="7" y1="7" x2="12" y2="9" stroke="#333" stroke-width="1.2"/><line x1="7" y1="9" x2="12" y2="7" stroke="#333" stroke-width="1.2"/></svg>',
        copy: '<svg viewBox="0 0 16 16"><rect x="4" y="4" width="8" height="8" rx="1" fill="none" stroke="#333" stroke-width="1.2"/><rect x="6" y="2" width="8" height="8" rx="1" fill="none" stroke="#333" stroke-width="1.2" stroke-dasharray="1,1"/></svg>',
        paste: '<svg viewBox="0 0 16 16"><rect x="4" y="3" width="8" height="11" rx="1" fill="none" stroke="#333" stroke-width="1.2"/><line x1="6" y1="3" x2="6" y2="2" stroke="#333" stroke-width="1.2"/><line x1="10" y1="3" x2="10" y2="2" stroke="#333" stroke-width="1.2"/></svg>',
        print: '<svg viewBox="0 0 16 16"><path d="M4 6h8v5h-1v3H5v-3H4z" fill="none" stroke="#333" stroke-width="1.2"/><line x1="5" y1="8" x2="11" y2="8" stroke="#333" stroke-width="1"/></svg>',
        indent: '<svg viewBox="0 0 16 16"><line x1="2" y1="4" x2="14" y2="4" stroke="#333" stroke-width="1.2"/><line x1="6" y1="8" x2="14" y2="8" stroke="#333" stroke-width="1.2"/><line x1="6" y1="12" x2="14" y2="12" stroke="#333" stroke-width="1.2"/><polygon points="4,9 2,11 4,13" fill="#333"/></svg>',
        outdent: '<svg viewBox="0 0 16 16"><line x1="2" y1="4" x2="14" y2="4" stroke="#333" stroke-width="1.2"/><line x1="4" y1="8" x2="12" y2="8" stroke="#333" stroke-width="1.2"/><line x1="4" y1="12" x2="12" y2="12" stroke="#333" stroke-width="1.2"/><polygon points="2,9 4,11 2,13" fill="#333"/></svg>',
        ltr: '<svg viewBox="0 0 16 16"><line x1="3" y1="8" x2="13" y2="8" stroke="#333" stroke-width="1.5"/><polygon points="11,5 14,8 11,11" fill="#333"/></svg>',
        rtl: '<svg viewBox="0 0 16 16"><line x1="3" y1="8" x2="13" y2="8" stroke="#333" stroke-width="1.5"/><polygon points="5,5 2,8 5,11" fill="#333"/></svg>',
        maximize: '<svg viewBox="0 0 16 16"><path d="M3 3h4v2H5v2H3zM13 13H9v2h2v-2h2zM3 3v4h2V5h2V3zM13 13V9h-2v2h-2v2z" fill="#333"/></svg>',
        removeformat: '<svg viewBox="0 0 16 16"><line x1="4" y1="4" x2="12" y2="4" stroke="#333" stroke-width="1.2"/><line x1="6" y1="8" x2="10" y2="8" stroke="#333" stroke-width="1.2"/><line x1="7" y1="12" x2="9" y2="12" stroke="#333" stroke-width="1.2"/><line x1="3" y1="3" x2="12" y2="13" stroke="#333" stroke-width="1.5"/></svg>',
        pastetext: '<svg viewBox="0 0 16 16"><rect x="4" y="3" width="8" height="11" rx="1" fill="none" stroke="#333" stroke-width="1.2"/><line x1="6" y1="6" x2="10" y2="6" stroke="#333" stroke-width="1"/><line x1="6" y1="9" x2="10" y2="9" stroke="#333" stroke-width="1"/><line x1="6" y1="12" x2="8" y2="12" stroke="#333" stroke-width="1"/></svg>',
        time: '<svg viewBox="0 0 16 16"><circle cx="8" cy="9" r="5" fill="none" stroke="#333" stroke-width="1.2"/><line x1="8" y1="6" x2="8" y2="9" stroke="#333" stroke-width="1.2"/><line x1="8" y1="9" x2="10" y2="11" stroke="#333" stroke-width="1.2"/><line x1="6" y1="2" x2="10" y2="2" stroke="#333" stroke-width="1.2"/></svg>',
        date: '<svg viewBox="0 0 16 16"><rect x="3" y="4" width="10" height="9" rx="1" fill="none" stroke="#333" stroke-width="1.2"/><line x1="3" y1="7" x2="13" y2="7" stroke="#333" stroke-width="1.2"/><line x1="5" y1="2" x2="5" y2="4" stroke="#333" stroke-width="1.2"/><line x1="11" y1="2" x2="11" y2="4" stroke="#333" stroke-width="1.2"/></svg>',
        email: '<svg viewBox="0 0 16 16"><rect x="2" y="4" width="12" height="8" rx="1" fill="none" stroke="#333" stroke-width="1.2"/><polyline points="2,5 8,9 14,5" stroke="#333" stroke-width="1.2" fill="none"/></svg>',
        youtube: '<svg viewBox="0 0 16 16"><rect x="2" y="4" width="12" height="8" rx="2" fill="none" stroke="#333" stroke-width="1.2"/><polygon points="7,6 11,8 7,10" fill="#333"/></svg>',
        grip: '<svg viewBox="0 0 16 16"><line x1="4" y1="5" x2="12" y2="5" stroke="#999" stroke-width="1.5"/><line x1="4" y1="8" x2="12" y2="8" stroke="#999" stroke-width="1.5"/><line x1="4" y1="11" x2="12" y2="11" stroke="#999" stroke-width="1.5"/></svg>'
    };

    var IconSet = function() {};

    IconSet.prototype.create = function(name) {
        if (!iconPaths[name]) {
            return null;
        }
        var wrapper = document.createElement("div");
        wrapper.innerHTML = iconPaths[name];
        var svg = wrapper.firstChild;
        if (svg) {
            svg.setAttribute("class", "sceditor-icon");
            svg.style.fill = "#333";
        }
        return svg;
    };

    if (window.sceditor && window.sceditor.icons) {
        window.sceditor.icons.default = IconSet;
    }
})();
