// Compare groups: what the average-life window is and why, in words. The
// window is where every group's curve still has data: by default the last
// time seen in the group whose data ends first.

// ``window`` is the formatted window with its unit ("1,233 cycles").
export function windowText(result, window) {
  const g = result.tau_group;
  const ends = g != null ? ` the last time seen in group ${g}, whose data ends first` : "";
  const past = g != null ? `Past it, group ${g}'s curve has no data, so averages over longer would be guesses.`
    : "Past it, a group's curve has no data.";
  if (result.tau_source === "auto") {
    return `Window ${window}, set automatically:${ends || " the shortest group's last time"}. ${past} `
      + "Type a shorter Window to compare over less time.";
  }
  if (result.tau_source === "capped") {
    return `Window ${window}: the one you typed was longer, so it was cut to${ends || " the shortest group's last time"}. ${past}`;
  }
  return `Window ${window}, as you set it. Average lives count time up to it only.`;
}
