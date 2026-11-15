import com.android.apksig.ApkSigner;
import com.android.apksig.ApkVerifier;
import java.io.File;
import java.io.FileInputStream;
import java.security.KeyStore;
import java.security.PrivateKey;
import java.security.cert.X509Certificate;
import java.util.Collections;

/** Tanda tangani APK (v1+v2+v3) memakai apksig, lalu verifikasi. */
public class Sign {
  public static void main(String[] a) throws Exception {
    if (a.length < 5) { System.err.println("Sign <in.apk> <out.apk> <keystore.p12> <alias> <password> [minSdk]"); System.exit(2); }
    char[] pw = a[4].toCharArray();
    KeyStore ks = KeyStore.getInstance("PKCS12");
    try (FileInputStream in = new FileInputStream(a[2])) { ks.load(in, pw); }
    PrivateKey key = (PrivateKey) ks.getKey(a[3], pw);
    X509Certificate cert = (X509Certificate) ks.getCertificate(a[3]);
    ApkSigner.SignerConfig sc = new ApkSigner.SignerConfig.Builder("CLIPAGNT", key, Collections.singletonList(cert)).build();
    int minSdk = a.length > 5 ? Integer.parseInt(a[5]) : 24;
    new ApkSigner.Builder(Collections.singletonList(sc))
        .setInputApk(new File(a[0])).setOutputApk(new File(a[1])).setMinSdkVersion(minSdk)
        .setV1SigningEnabled(true).setV2SigningEnabled(true).setV3SigningEnabled(true)
        .build().sign();
    ApkVerifier.Result r = new ApkVerifier.Builder(new File(a[1])).build().verify();
    System.out.println("verified=" + r.isVerified() + " v1=" + r.isVerifiedUsingV1Scheme()
        + " v2=" + r.isVerifiedUsingV2Scheme() + " v3=" + r.isVerifiedUsingV3Scheme());
    for (ApkVerifier.IssueWithParams e : r.getErrors()) System.out.println("ERROR " + e);
    if (!r.isVerified()) System.exit(1);
  }
}
