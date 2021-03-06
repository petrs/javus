/* Fully copied!  */
package com.dumpmemapplet;

// import javacard.framework.*;

// public class DumpMemApplet extends Applet {
//     private static final byte INS_SUCCESS = 0x01;
//     private static final byte INS_FAILURE = 0x02;

//     byte[] success = {(byte) 0x01, (byte) 0x02, (byte) 0x01, (byte) 0x02};
//     byte[] failure = {(byte) 0x80, (byte) 0x40, (byte) 0x80, (byte) 0x40};
//     short msgLen = 4;

//     public static void install(byte[] array, short off, byte len) {
//         new DumpMemApplet().register();
//     }
//     public void process(APDU apdu) {
//         if (selectingApplet()) { return; }

//         byte[] buf = apdu.getBuffer();
//         switch (buf[ISO7816.OFFSET_INS]) {
//             case INS_SUCCESS:
//                 Util.arrayCopyNonAtomic(success, (short) 0, buf, (short) 0, msgLen);
//                 apdu.setOutgoingAndSend((short) 0, (short) 4);
//                 break;
//             case INS_FAILURE:
//                 Util.arrayCopyNonAtomic(failure, (short) 0, buf, (short) 0, msgLen);
//                 apdu.setOutgoingAndSend((short) 0, (short) 4);
//                 break;
//             default:
//                 ISOException.throwIt(ISO7816.SW_INS_NOT_SUPPORTED);
//         }
//     }
// }

import javacard.framework.*;

public class DumpMemApplet extends Applet {
  // custom for checks
  private static final byte INS_SUCCESS = 0x08;
  private static final byte INS_FAILURE = 0x0f;

  byte[] success = {(byte) 0x01, (byte) 0x02, (byte) 0x01, (byte) 0x02};
  byte[] failure = {(byte) 0x80, (byte) 0x40, (byte) 0x80, (byte) 0x40};
  short msgLen = 4;

  private static final byte INS_PREPARE1 = 0x01;
  private static final byte INS_PREPARE2 = 0x02;
  private static final byte INS_READMEM = 0x04;
  private static final short TEST_LEN = 128;
  private short[] arrayS;
  private byte[] arrayB;
  private byte[] arrayMutable;
  private short index;

  public static void install(byte[] array, short off, byte len) {
    new DumpMemApplet().register();
  }

  public void process(APDU apdu) {
    if (selectingApplet()) {
      return;
    }
    byte[] buf = apdu.getBuffer();
    switch (buf[ISO7816.OFFSET_INS]) {
      case INS_PREPARE1:
        arrayMutable = new byte[2];
        short[] arraySlocal = null;
        JCSystem.beginTransaction();
        arrayS = new short[1];
        arraySlocal = arrayS;
        JCSystem.abortTransaction();
        arrayB = new byte[TEST_LEN];
        arrayS = arraySlocal;
        if ((Object) arrayS == (Object) arrayB) {
          Util.setShort(buf, (short) 0, (short) arrayB.length);
          Util.setShort(buf, (short) 2, (short) arrayS.length);
          apdu.setOutgoingAndSend((short) 0, (short) 4);
        } else {
          ISOException.throwIt(ISO7816.SW_WRONG_DATA);
        }
        break;
      case INS_PREPARE2:
        copyArray(true);
        index = findIndex();
        Util.setShort(buf, (short) 0, index);
        apdu.setOutgoingAndSend((short) 0, (short) 2);
        break;
      case INS_READMEM:
        byte p1 = buf[ISO7816.OFFSET_P1];
        byte p2 = buf[ISO7816.OFFSET_P2];
        apdu.setIncomingAndReceive();
        short len = Util.getShort(buf, ISO7816.OFFSET_CDATA);
        setupArray(index, p1, p2, len);
        copyArray(false);
        Util.arrayCopyNonAtomic(arrayMutable, (short) 0, buf, (short) 0, len);
        apdu.setOutgoingAndSend((short) 0, len);
        break;
      case INS_SUCCESS:
        Util.arrayCopyNonAtomic(success, (short) 0, buf, (short) 0, msgLen);
        apdu.setOutgoingAndSend((short) 0, (short) 4);
        break;
      case INS_FAILURE:
        Util.arrayCopyNonAtomic(failure, (short) 0, buf, (short) 0, msgLen);
        apdu.setOutgoingAndSend((short) 0, (short) 4);
        break;
      default:
        ISOException.throwIt(ISO7816.SW_INS_NOT_SUPPORTED);
    }
  }

  private void copyArray(boolean from) {
    short half = (short) (arrayS.length / 2);
    for (short i = 0; i < half; i++) {
      if (from) {
        Util.setShort(arrayB, (short) (i * 2), arrayS[(short) (half + i)]);
      } else {
        arrayS[(short) (half + i)] = Util.getShort(arrayB, (short) (i * 2));
      }
    }
  }

  private short findIndex() {
    for (short i = 0; i < arrayB.length; i++) {
      if (arrayB[i] == (byte) 0x0B
          && arrayB[(short) (i + 1)] == (byte) 0x80
          && arrayB[(short) (i + 2)] == (byte) 0x02) {
        return i;
      }
    }
    return -1;
  }

  private void setupArray(short index, byte p1, byte p2, short length) {
    Util.setShort(arrayB, (short) (index + 1), length);
    arrayB[(short) (index + 1)] |= (byte) 0x80;
    arrayB[(short) (index + 3)] = p1;
    arrayB[(short) (index + 4)] = p2;
  }
}
