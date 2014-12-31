/*
 Copyright © 2014 José Luis Zabalza  License LGPLv3+: GNU
 LGPL version 3 or later <http://www.gnu.org/copyleft/lgpl.html>.
 This is free software: you are free to change and redistribute it.
 There is NO WARRANTY, to the extent permitted by law.
*/
// [][][][][][][][][][][][][][][][][][][][][][][][][][][][][][][][][][]
// []
// []       i2c LCD library Display Test Demo
// []	    Based on a  dale@wentztech.com work
// []
// []
// [][][][][][][][][][][][][][][][][][][][][][][][][][][][][][][][][][]


#define VERSION "1.1"

#include <Wire.h>
#include <inttypes.h>

#include <LCDi2c_PCF2119x.h>

LCDi2c_PCF2119x lcd = LCDi2c_PCF2119x(2,16,0x3B);

uint8_t rows = 2;
uint8_t cols = 16;


void setup()
{
    lcd.init();                          // Init the display, clears the display

    lcd.print("Hello World!");       // Classic Hello World!

    delay(1000);
}


void loop()
{
    lcdtest_basic();
}


void lcdtest_basic()
{

    lcd.clear();
    lcd.print ("Cursor Test");
    delay(1000);
    Cursor_Type();

    lcd.clear();
    lcd.print("Characters Test");
    delay(1000);
    Characters();
    delay(1000);

    lcd.clear();
    lcd.print("Every Line");
    delay(1000);
    Every_Line(rows);
    delay(1000);

    lcd.clear();
    lcd.print("Every Position");
    delay(1000);
    Every_Pos(rows,cols);
    delay(1000);

}

void Cursor_Type()
{
    lcd.setCursor(0,0);
    lcd.print("Underline Cursor");
    lcd.setCursor(1,0);
    lcd.cursor_on();
    delay(1000);
    lcd.cursor_off();
    lcd.setCursor(0,0);

    lcd.print("Block Cursor    ");
    lcd.setCursor(1,0);
    lcd.blink_on();
    delay(1000);
    lcd.blink_off();
    lcd.setCursor(0,0);

    lcd.print("No Cursor      ");
    lcd.setCursor(1,0);
    delay(1000);
}

void Count_Numbers()
{
    lcd.clear();
    lcd.print("Count to 255");

    for (int i=0;i<255;i++)
    {
        lcd.setCursor(1,0);

        lcd.print(i,DEC);

        lcd.setCursor(1,7);

        lcd.print(i,BIN);

        // delay(10);
    }
}

void Characters()
{
    int  chartoprint=48;
    char a;

    lcd.clear();

    for(int i=0 ; i < rows ; i++)
    {
        for(int j=0 ; j < cols ; j++)
        {
            lcd.setCursor(i,j);
            a = char(chartoprint);
            lcd.print(char(chartoprint));
            chartoprint++;
            if(chartoprint == 127)
                return;
        }
    }
}


void Fancy_Clear()
{
    for (int i=0 ; i < rows ; i++)
    {
        for(int j=0 ; j < cols/2 ; j++)
        {
            lcd.setCursor(i,j);
            lcd.print(" ");

            lcd.setCursor(i, cols - j);
            lcd.print(" ");
        }
        //delay(10);
    }
}

void Every_Line(int lines)
{
    lcd.clear();
    for(int i=0 ; i < lines ; i++)
    {
        lcd.setCursor(i,0);
        lcd.print("Line : ");
        lcd.print(i,DEC);
    }
}

void Every_Pos(int lines,int cols)
{
    lcd.clear();

    for(int i=0 ; i < lines ; i++)
    {
        for(int j=0 ; j< cols ; j++)
        {
            lcd.setCursor(i,j);
            lcd.print(i,DEC);
        }
    }
}