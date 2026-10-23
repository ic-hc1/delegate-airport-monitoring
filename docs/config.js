// Shared-sync settings for the arrivals board.
// Leave `firebase: null` and each volunteer's met checks and notes stay on their own device
// (with Export / Import to pass them on). To sync every volunteer live, create a free Firebase
// project (see dashboard/README.md), then paste its web-app config here, for example:
//   firebase: { apiKey: "...", authDomain: "xxx.firebaseapp.com", projectId: "xxx", appId: "..." }
window.ARRIVALS_CONFIG = {
  firebase: {
    apiKey: "AIzaSyDchxCoxvy589cAqAZJ_2tLnKq5-IOhMGQ",
    authDomain: "hc1-airport.firebaseapp.com",
    projectId: "hc1-airport",
    storageBucket: "hc1-airport.firebasestorage.app",
    messagingSenderId: "427846526598",
    appId: "1:427846526598:web:3f049725282a71b6f61307",
  },
};
