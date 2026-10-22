// Shared-sync settings for the arrivals board.
// Leave `firebase: null` and each volunteer's met checks and notes stay on their own device
// (with Export / Import to pass them on). To sync every volunteer live, create a free Firebase
// project (see dashboard/README.md), then paste its web-app config here, for example:
//   firebase: { apiKey: "...", authDomain: "xxx.firebaseapp.com", projectId: "xxx", appId: "..." }
window.ARRIVALS_CONFIG = {
  firebase: null,
};
