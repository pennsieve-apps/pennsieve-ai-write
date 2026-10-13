%% biorxiv-preprint.cls — a clean preprint layout for bioRxiv submissions.
%%
%% Adapted from the CC0 "Preprint_template" by its author at NYU Langone
%% Health, who placed it in the public domain with no restrictions and offered
%% no support. CC0 asks for nothing in return, but the good parts here are
%% theirs: the cleveref set-up, the phantom subpanel trick that makes
%% "Figure 1A" a working hyperlink, the caption and section styling, and the
%% shape of the page. This file is MIT, like the rest of this repository.
%%
%% What was changed:
%%   - The institutional violet and blue became a neutral navy and charcoal.
%%   - Montserrat became Helvetica (helvet). Montserrat lives in
%%     texlive-fonts-extra, which is 1.86GB on its own, against 198MB for
%%     everything else this file needs.
%%   - natbib and the .bib file are gone. Manuscripts here carry their
%%     citations inline and their references as a list, so there is no
%%     bibliography pass to go wrong.
%%   - A front matter block was added for the generated fields: affiliations,
%%     correspondence, the deposit's DOI and the bioRxiv article category.
%%
%% bioRxiv does not typeset submissions. Whatever PDF is uploaded is exactly
%% what readers see, so there is no house style to match.
%%
%% Engine: pdflatex, through latexmk. No fontspec, no XeTeX-only packages.
%%
%% Options:
%%   twocolumn    two-column body
%%   lineno       numbered lines, for sending to reviewers
%%   doublespace  double-spaced body, also for review
%%
%% The document supplies \title, \author, \affiliation{n}{text},
%% \corresponding{email}, \datadoi{doi}, \runningtitle{short title} and
%% \category{New Results}, then opens with \makefrontmatter{<abstract>}.
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{biorxiv-preprint}[2026/10/13 bioRxiv preprint layout]

\newif\ifbxv@twocol \bxv@twocolfalse
\newif\ifbxv@lineno \bxv@linenofalse
\newif\ifbxv@dspace \bxv@dspacefalse
\DeclareOption{twocolumn}{\bxv@twocoltrue\PassOptionsToClass{twocolumn}{extarticle}}
\DeclareOption{lineno}{\bxv@linenotrue}
\DeclareOption{doublespace}{\bxv@dspacetrue}
\DeclareOption*{\PassOptionsToClass{\CurrentOption}{extarticle}}
\ProcessOptions\relax
% extarticle for the wider range of body sizes, falling back to article where
% the extsizes package is not installed.
\IfFileExists{extarticle.cls}
  {\LoadClass[9pt,letterpaper]{extarticle}}
  {\LoadClass[10pt,letterpaper]{article}}

% ---------------------------------------------------------------- packages
\RequirePackage[T1]{fontenc}
\RequirePackage[utf8]{inputenc}
\RequirePackage[scaled=0.92]{helvet}
\IfFileExists{lmodern.sty}{\RequirePackage{lmodern}}{}
\RequirePackage[left=0.8in,right=0.8in,top=0.75in,bottom=0.85in]{geometry}
\RequirePackage{graphicx}
\RequirePackage[table]{xcolor}
\RequirePackage{booktabs}
\RequirePackage{longtable}
\RequirePackage{array}
\RequirePackage{amsmath}
\RequirePackage{amssymb}
\RequirePackage{multicol}
\RequirePackage{setspace}
\RequirePackage{textcomp}
\RequirePackage[font=small,labelfont=bf,labelsep=colon,justification=raggedright,
                singlelinecheck=false]{caption}
\RequirePackage[labelfont=normalfont]{subcaption}
% Pandoc emits these, so a generated body never fails on them.
\providecommand{\tightlist}{\setlength{\itemsep}{0pt}\setlength{\parskip}{0pt}}
\providecommand{\pandocbounded}[1]{#1}

\definecolor{Highlight}{HTML}{1B2A41}  % headings and caption labels: dark navy
\definecolor{Accent}{HTML}{2F5D8F}     % links and superscripts: navy
\definecolor{Muted}{HTML}{55606D}

\RequirePackage[colorlinks=true,breaklinks=true,citecolor=Accent,
                linkcolor=Accent,urlcolor=Accent]{hyperref}
\RequirePackage{url}
\urlstyle{same}

% Optional throughout: each of these lives in a larger TeX package, and the
% class has to build on a minimal installation as well as in the image.
\IfFileExists{ragged2e.sty}{\RequirePackage[document]{ragged2e}}{}
\IfFileExists{microtype.sty}{\RequirePackage{microtype}}{}
\IfFileExists{changepage.sty}{\RequirePackage{changepage}}{}
\IfFileExists{enumitem.sty}{\RequirePackage{enumitem}%
  \setlist{itemsep=1pt,parsep=0pt,topsep=4pt}}{}
\IfFileExists{grffile.sty}{\RequirePackage{grffile}}{}
\IfFileExists{pdflscape.sty}{\RequirePackage{pdflscape}}{}
% cleveref is the reason for this template: \Cref{fig:1A} prints "Figure 1A"
% and links to it. It has to be loaded after hyperref.
\IfFileExists{cleveref.sty}{\RequirePackage[noabbrev,nameinlink]{cleveref}}{%
  \providecommand{\Cref}[1]{\ref{#1}}\providecommand{\cref}[1]{\ref{#1}}}
\ifbxv@lineno
  \IfFileExists{lineno.sty}{\RequirePackage{lineno}%
    \renewcommand\linenumberfont{\normalfont\small}\linenumbers}{%
    \ClassWarningNoLine{biorxiv-preprint}{lineno.sty not found; no line numbers}}
\fi

% Subpanel letters, so \Cref{fig:1A} reads "Figure 1A". A figure declares one
% \phantomcaption\label{} per panel inside a subcaptiongroup.
\renewcommand{\thesubfigure}{\Alph{subfigure}}
\captionsetup[subfigure]{subrefformat=simple,labelformat=simple}
\captionsetup{labelfont={color=Highlight,bf}}

% ------------------------------------------------------------ title block
\newcommand{\bxv@affiliations}{}
\newcommand{\affiliation}[2]{%
  \g@addto@macro\bxv@affiliations{\textcolor{Accent}{\textsuperscript{#1}}#2\par}}
\newcommand{\bxv@corresponding}{}
\newcommand{\corresponding}[1]{\renewcommand{\bxv@corresponding}{#1}}
\newcommand{\bxv@datadoi}{}
\newcommand{\datadoi}[1]{\renewcommand{\bxv@datadoi}{#1}}
\newcommand{\bxv@category}{New Results}
\newcommand{\category}[1]{\renewcommand{\bxv@category}{#1}}
\newcommand{\bxv@runningtitle}{Preprint}
\newcommand{\runningtitle}[1]{\renewcommand{\bxv@runningtitle}{#1}}

\newcommand{\bxv@titleblock}{%
  \begingroup\setlength{\parindent}{0pt}\raggedright
  {\sffamily\footnotesize\color{Muted}\MakeUppercase{\bxv@category}\par}
  \vspace{3pt}
  % No setspace environment around the title. Its \par at \begin ends the
  % paragraph before the new size takes hold, which drops the title back to
  % body size and leaves the author line riding up into it. The second
  % argument of \fontsize is the leading, so the tight title spacing the
  % template wanted comes from there instead.
  {\sffamily\bfseries\fontsize{20}{23}\selectfont\color{Highlight}\@title\par}
  \vspace{5pt}
  {\sffamily\small\@author\par}
  \vspace{6pt}
  {\footnotesize\color{Muted}\bxv@affiliations}
  \ifx\bxv@corresponding\@empty\else
    {\footnotesize\color{Muted}Correspondence:
     \href{mailto:\bxv@corresponding}{\bxv@corresponding}\par}\fi
  \ifx\bxv@datadoi\@empty\else
    {\footnotesize\color{Muted}Data:
     \href{https://doi.org/\bxv@datadoi}{doi:\bxv@datadoi}\par}\fi
  \vspace{7pt}{\color{Accent}\hrule height 1pt}\vspace{10pt}
  \endgroup}

\newcommand{\bxv@abstractblock}[1]{%
  \begingroup\small
  {\sffamily\bfseries\footnotesize\color{Highlight}ABSTRACT}\par\vspace{3pt}
  #1\par
  \vspace{8pt}{\color{Highlight}\hrule height 0.4pt}\vspace{11pt}\endgroup}

% One command, because in two columns the title and abstract span both and so
% have to be set together.
\newcommand{\makefrontmatter}[1]{%
  \ifbxv@twocol
    \twocolumn[\bxv@titleblock\bxv@abstractblock{#1}]%
  \else
    \bxv@titleblock\bxv@abstractblock{#1}%
  \fi
  % Without this a float asking for the top of the page lands above the title.
  \suppressfloats[t]%
  \thispagestyle{bxvfirst}%
  \ifbxv@dspace\doublespacing\fi}

% ------------------------------------------------------------- headings
\IfFileExists{titlesec.sty}{%
  \RequirePackage{titlesec}%
  \titleformat{\section}{\sffamily\normalsize\bfseries\color{Highlight}}%
    {\thesection}{0.8em}{\MakeUppercase}
  \titleformat{\subsection}{\sffamily\normalsize\bfseries\color{Highlight}}%
    {\thesubsection}{0.8em}{}
  \titleformat{\subsubsection}{\sffamily\small\itshape\color{Highlight}}%
    {\thesubsubsection}{0.8em}{}
  \titlespacing*{\section}{0pt}{12pt plus 3pt minus 2pt}{4pt}
  \titlespacing*{\subsection}{0pt}{9pt plus 2pt minus 2pt}{2pt}
  \titlespacing*{\subsubsection}{0pt}{7pt plus 2pt minus 2pt}{1pt}%
}{%
  \renewcommand{\section}{\@startsection{section}{1}{0pt}%
    {12pt plus 3pt minus 2pt}{4pt}{\sffamily\normalsize\bfseries\color{Highlight}}}
  \renewcommand{\subsection}{\@startsection{subsection}{2}{0pt}%
    {9pt plus 2pt minus 2pt}{2pt}{\sffamily\normalsize\bfseries\color{Highlight}}}
  \renewcommand{\subsubsection}{\@startsection{subsubsection}{3}{0pt}%
    {7pt plus 2pt minus 2pt}{1pt}{\sffamily\small\itshape\color{Highlight}}}%
}
% The template numbers nothing, and a preprint reads better with plain headings.
\setcounter{secnumdepth}{0}

% --------------------------------------------------------- page furniture
\RequirePackage{fancyhdr}
\fancypagestyle{bxvfirst}{%
  \fancyhf{}\renewcommand{\headrulewidth}{0pt}
  \fancyfoot[L]{\footnotesize\color{Muted}Preprint \textbar{} \today}
  \fancyfoot[R]{\footnotesize\color{Muted}\thepage}}
\fancypagestyle{bxvbody}{%
  \fancyhf{}\renewcommand{\headrulewidth}{0pt}
  \fancyhead[L]{\footnotesize\sffamily\color{Muted}\bxv@runningtitle}
  \fancyhead[R]{\footnotesize\sffamily\color{Muted}Preprint}
  \fancyfoot[R]{\footnotesize\color{Muted}\thepage}}
\pagestyle{bxvbody}

% Supplementary figures, tables and equations renumber as S1, S2 and so on.
\newcommand{\beginsupplement}{%
  \setcounter{figure}{0}\renewcommand{\thefigure}{S\arabic{figure}}%
  \setcounter{table}{0}\renewcommand{\thetable}{S\arabic{table}}%
  \setcounter{equation}{0}\renewcommand{\theequation}{S\arabic{equation}}}

\setlength{\parindent}{0pt}
\setlength{\parskip}{0.75ex plus 0.25ex minus 0.25ex}
\renewcommand{\arraystretch}{1.15}
\endinput
