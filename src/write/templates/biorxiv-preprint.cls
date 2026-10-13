%% biorxiv-preprint.cls — a clean preprint look for bioRxiv submissions.
%%
%% Written for the Pennsieve AI Co-Scientist and released under the same MIT
%% licence as the rest of this repository. It is not copied from any existing
%% template, because the widely circulated bioRxiv classes carry licences that
%% do not sit with an MIT repository: the quantixed template is GPL-3.0 and
%% the thelovelab fork states no licence at all.
%%
%% bioRxiv does not typeset submissions. Whatever PDF is uploaded is exactly
%% what readers see, so there is no house style to match. This class aims only
%% to be clean, readable and self-contained.
%%
%% Engine: pdflatex, via latexmk, the same toolchain as the lab's other
%% manuscripts. No fontspec, no XeTeX-only packages.
%%
%% Options:
%%   twocolumn  two-column body, the usual preprint look (default is one)
%%   lineno     numbered lines, for sending to reviewers
%%   11pt/12pt  larger body text (default 10pt)
%%
%% Commands the document supplies:
%%   \title, \author, \affiliation{n}{text}, \corresponding{email},
%%   \datadoi{doi}, \runningtitle{short title}, \category{New Results}
%% and opens the paper with \makefrontmatter{<abstract text>} in place of
%% \maketitle, because in two columns the two must be set together.
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{biorxiv-preprint}[2026/10/13 bioRxiv preprint layout]

\newif\ifbxv@twocol \bxv@twocolfalse
\newif\ifbxv@lineno \bxv@linenofalse
\DeclareOption{twocolumn}{\bxv@twocoltrue}
\DeclareOption{lineno}{\bxv@linenotrue}
\DeclareOption*{\PassOptionsToClass{\CurrentOption}{article}}
\ProcessOptions\relax
\LoadClass[10pt,a4paper]{article}
\ifbxv@twocol\RequirePackage{multicol}\fi

% ---------------------------------------------------------------- packages
\RequirePackage[T1]{fontenc}
\RequirePackage[utf8]{inputenc}
% lmodern, titlesec and enumitem are not in a minimal TeX installation, and
% the class should still build there, so each one is optional.
\IfFileExists{lmodern.sty}{\RequirePackage{lmodern}}{}
\RequirePackage[scaled=0.92]{helvet}
\IfFileExists{microtype.sty}{\RequirePackage{microtype}}{}
\RequirePackage[margin=1in,top=0.9in,bottom=1in]{geometry}
\RequirePackage{graphicx}
\RequirePackage{xcolor}
\RequirePackage{booktabs}
\RequirePackage{longtable}
\RequirePackage{array}
\RequirePackage{amsmath}
\RequirePackage{amssymb}
\RequirePackage{fancyhdr}
\RequirePackage[font=small,labelfont=bf,labelsep=period]{caption}
\RequirePackage{textcomp}
% Pandoc emits \tightlist and, for images with sizes, these two.
\providecommand{\tightlist}{\setlength{\itemsep}{0pt}\setlength{\parskip}{0pt}}
\providecommand{\pandocbounded}[1]{#1}
\RequirePackage[colorlinks=true,allcolors=bxvlink,breaklinks=true]{hyperref}
\RequirePackage{url}
\urlstyle{same}

% Line numbers are only for review copies, and lineno is not in every
% TeX installation, so never fail the build over it.
\ifbxv@lineno
  \IfFileExists{lineno.sty}{\RequirePackage{lineno}\linenumbers}{%
    \ClassWarningNoLine{biorxiv-preprint}{lineno.sty not found; no line numbers}}
\fi

\definecolor{bxvlink}{HTML}{1A4F8B}
\definecolor{bxvrule}{HTML}{C8D0D8}
\definecolor{bxvmut}{HTML}{55606D}

% ------------------------------------------------------------ title block
\newcommand{\bxv@affiliations}{}
\newcommand{\affiliation}[2]{%
  \g@addto@macro\bxv@affiliations{\textsuperscript{#1}#2\par}}
\newcommand{\bxv@corresponding}{}
\newcommand{\corresponding}[1]{\renewcommand{\bxv@corresponding}{#1}}
\newcommand{\bxv@datadoi}{}
\newcommand{\datadoi}[1]{\renewcommand{\bxv@datadoi}{#1}}
\newcommand{\bxv@category}{New Results}
\newcommand{\category}[1]{\renewcommand{\bxv@category}{#1}}
\newcommand{\bxv@runningtitle}{Preprint}
\newcommand{\runningtitle}[1]{\renewcommand{\bxv@runningtitle}{#1}}

\newcommand{\bxv@titleblock}{%
  \begingroup
  \raggedright
  {\color{bxvmut}\sffamily\footnotesize\MakeUppercase{\bxv@category}\par}
  \vspace{2pt}
  {\sffamily\bfseries\fontsize{19}{23}\selectfont\@title\par}
  \vspace{9pt}
  {\sffamily\small\@author\par}
  \vspace{7pt}
  {\footnotesize\color{bxvmut}\bxv@affiliations}
  \ifx\bxv@corresponding\@empty\else
    {\footnotesize\color{bxvmut}Correspondence: \href{mailto:\bxv@corresponding}{\bxv@corresponding}\par}
  \fi
  \ifx\bxv@datadoi\@empty\else
    {\footnotesize\color{bxvmut}Data: \href{https://doi.org/\bxv@datadoi}{doi:\bxv@datadoi}\par}
  \fi
  \vspace{6pt}
  {\color{bxvrule}\hrule height 0.8pt}
  \vspace{10pt}
  \endgroup}

\newcommand{\bxv@abstractblock}[1]{%
  \begingroup\small
  {\sffamily\bfseries\footnotesize ABSTRACT}\par\vspace{3pt}
  #1\par
  \vspace{8pt}{\color{bxvrule}\hrule height 0.4pt}\vspace{12pt}
  \endgroup}

% The whole front matter in one command, because in two-column mode the title
% and abstract have to span both columns and so must be set together.
\newcommand{\makefrontmatter}[1]{%
  \ifbxv@twocol
    \twocolumn[\bxv@titleblock\bxv@abstractblock{#1}]%
  \else
    \bxv@titleblock\bxv@abstractblock{#1}%
  \fi
  % Without this a float asking for the top of the page lands above the
  % title block, which looks like a layout bug in a one-column paper.
  \suppressfloats[t]%
  \thispagestyle{bxvfirst}}

% ------------------------------------------------------------- headings
\IfFileExists{titlesec.sty}{%
  \RequirePackage{titlesec}%
  \titleformat{\section}{\sffamily\bfseries\large}{\thesection.}{0.5em}{}
  \titleformat{\subsection}{\sffamily\bfseries\normalsize}{\thesubsection}{0.5em}{}
  \titleformat{\subsubsection}{\sffamily\itshape\normalsize}{}{0em}{}
  \titlespacing*{\section}{0pt}{13pt plus 3pt minus 2pt}{5pt}
  \titlespacing*{\subsection}{0pt}{10pt plus 2pt minus 2pt}{3pt}%
}{%
  % Same look without titlesec, which lives in a large TeX package that a
  % minimal installation does not carry.
  \renewcommand{\section}{\@startsection{section}{1}{0pt}%
    {13pt plus 3pt minus 2pt}{5pt}{\sffamily\bfseries\large}}
  \renewcommand{\subsection}{\@startsection{subsection}{2}{0pt}%
    {10pt plus 2pt minus 2pt}{3pt}{\sffamily\bfseries\normalsize}}
  \renewcommand{\subsubsection}{\@startsection{subsubsection}{3}{0pt}%
    {8pt plus 2pt minus 2pt}{2pt}{\sffamily\itshape\normalsize}}
  % titlesec prints "1." for a section and "1.1" for a subsection; match it.
  \expandafter\def\csname bxv@dot@section\endcsname{.}
  \def\@seccntformat##1{\csname the##1\endcsname
    \csname bxv@dot@##1\endcsname\hskip 0.5em}%
}

% --------------------------------------------------------------- running head
\fancypagestyle{bxvfirst}{%
  \fancyhf{}\renewcommand{\headrulewidth}{0pt}
  \fancyfoot[L]{\footnotesize\color{bxvmut}Preprint \textbar{} \today}
  \fancyfoot[R]{\footnotesize\color{bxvmut}\thepage}}
\fancypagestyle{bxvbody}{%
  \fancyhf{}\renewcommand{\headrulewidth}{0.4pt}
  \renewcommand{\headrule}{\color{bxvrule}\hrule height 0.4pt}
  \fancyhead[L]{\footnotesize\color{bxvmut}\sffamily\bxv@runningtitle}
  \fancyhead[R]{\footnotesize\color{bxvmut}\sffamily Preprint}
  \fancyfoot[R]{\footnotesize\color{bxvmut}\thepage}}
\pagestyle{bxvbody}

\setlength{\parindent}{0pt}
\setlength{\parskip}{5pt plus 1pt}
\IfFileExists{enumitem.sty}{%
  \RequirePackage{enumitem}\setlist{itemsep=1pt,parsep=0pt,topsep=4pt}}{%
  \setlength{\itemsep}{1pt}\setlength{\parsep}{0pt}\setlength{\topsep}{4pt}}
\renewcommand{\arraystretch}{1.15}
\endinput
