// A fit whose likelihood has no finite maximum (#230): the data don't pin the
// model down, so the numbers on the page aren't estimates. SurPyval 0.23
// recognises it for univariate (offset) fits, regression and accelerated-life
// fits; the backend sends { message, suggestion, detail } as
// result.no_finite_maximum. Shown above everything else on the result, so no
// use-level extrapolation or bound appears without it.
export default function NoMaximumNotice({ notice, style }) {
  if (!notice) return null;
  return (
    <div className="detail-note warn no-max-notice" role="alert" style={style}>
      <b>No finite maximum.</b> {notice.message}
      {notice.suggestion && <> {notice.suggestion}</>}
      {notice.detail && (
        <details>
          <summary>What SurPyval reported</summary>
          <p>{notice.detail}</p>
        </details>
      )}
    </div>
  );
}
